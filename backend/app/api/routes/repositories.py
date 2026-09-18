import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.routes.github import get_github_client
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.ingestion.pipeline import discover_and_normalize, exceeds_mvp_file_target
from app.ingestion.parsing_stage import parse_repository_files
from app.ingestion.security import ZipSafetyError, safe_extract
from app.github.client import GitHubClient
from app.github.errors import (
    GitHubAccessLost,
    GitHubApiError,
    GitHubBranchMissing,
    GitHubInstallationRevoked,
    GitHubRateLimited,
    GitHubRepositoryDeleted,
)
from app.models.github_installation import (
    GitHubInstallation,
    GitHubInstallationStatus,
)
from app.models.repository import (
    Repository,
    RepositoryAccessStatus,
    RepositorySourceType,
)
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.models.user import User
from app.sources.upload import UploadedRepositorySource
from app.sources.github import GitHubRepositorySource

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryImportResponse(BaseModel):
    repository_id: str
    index_id: str
    state: RepositoryIndexState
    size_warning: bool


class GitHubRepositoryImport(BaseModel):
    source_type: Literal["github"]
    github_repo_id: int
    branch: str | None = None


async def _mark_installation_revoked(
    db: AsyncSession, installation_id: uuid.UUID
) -> None:
    await db.execute(
        update(GitHubInstallation)
        .where(GitHubInstallation.id == installation_id)
        .values(status=GitHubInstallationStatus.REVOKED)
    )
    await db.execute(
        update(Repository)
        .where(Repository.github_installation_id == installation_id)
        .values(access_status=RepositoryAccessStatus.ACCESS_LOST)
    )
    await db.commit()


async def _mark_repository_access(
    db: AsyncSession,
    installation_id: uuid.UUID,
    github_repo_id: int | None,
    access_status: RepositoryAccessStatus,
) -> None:
    statement = update(Repository).where(
        Repository.github_installation_id == installation_id
    )
    if github_repo_id is not None:
        statement = statement.where(Repository.github_repo_id == github_repo_id)
    await db.execute(statement.values(access_status=access_status))
    await db.commit()


async def _save_upload(upload: UploadFile, path: Path, max_bytes: int) -> None:
    total = 0
    with path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="ZIP upload exceeds the configured size limit",
                )
            output.write(chunk)


async def _persist_repository(
    db: AsyncSession,
    current_user: User,
    source: UploadedRepositorySource | GitHubRepositorySource,
    source_ref: str,
    revision: str,
    name: str,
    default_branch: str,
    selected_branch: str,
    github_installation_id: uuid.UUID | None = None,
    github_repo_id: int | None = None,
) -> RepositoryImportResponse:
    repository = Repository(
        owner_id=current_user.id,
        github_installation_id=github_installation_id,
        source_type=RepositorySourceType(source.source_type),
        github_repo_id=github_repo_id,
        name=name,
        default_branch=default_branch,
        selected_branch=selected_branch,
        access_status=RepositoryAccessStatus.ACTIVE,
    )
    db.add(repository)
    await db.flush()
    repository_index = RepositoryIndex(
        repository_id=repository.id,
        version=1,
        revision=revision,
        state=RepositoryIndexState.PENDING,
    )
    db.add(repository_index)
    await db.flush()

    repository_index.state = RepositoryIndexState.DISCOVERING
    normalized = await discover_and_normalize(source, source_ref)
    repository_index.files_discovered = len(normalized)
    repository_index.files_processed = sum(
        item.status is RepositoryFileStatus.OK for item in normalized
    )
    repository_index.size_warning = exceeds_mvp_file_target(normalized)
    persisted_files: list[RepositoryFile] = []
    for item in normalized:
        repository_file = RepositoryFile(
            repository_index_id=repository_index.id,
            path=item.path,
            language=item.language,
            github_sha=item.github_sha,
            content_hash=item.content_hash,
            status=item.status,
            size_bytes=item.size_bytes,
            content=item.content,
        )
        db.add(repository_file)
        persisted_files.append(repository_file)
    await db.flush()
    repository_index.state = RepositoryIndexState.PARSING
    parsed_files = await parse_repository_files(persisted_files)
    repository_index.files_failed = sum(not item.parse_ok for item in parsed_files)
    repository_index.state = (
        RepositoryIndexState.PARTIAL
        if repository_index.files_failed
        else RepositoryIndexState.READY
    )
    await db.commit()

    return RepositoryImportResponse(
        repository_id=str(repository.id),
        index_id=str(repository_index.id),
        state=repository_index.state,
        size_warning=repository_index.size_warning,
    )


@router.post("", response_model=RepositoryImportResponse, status_code=201)
async def import_repository(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    github_client: Annotated[GitHubClient, Depends(get_github_client)],
) -> RepositoryImportResponse:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = GitHubRepositoryImport.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid GitHub import request") from exc
        installations = list(
            await db.scalars(
                select(GitHubInstallation).where(
                    GitHubInstallation.user_id == current_user.id,
                    GitHubInstallation.status == GitHubInstallationStatus.ACTIVE,
                ).order_by(GitHubInstallation.installation_id)
            )
        )
        selected_installation: GitHubInstallation | None = None
        metadata: dict | None = None
        revoked_seen = False
        for installation in installations:
            try:
                repositories = await github_client.list_repositories(
                    installation.installation_id
                )
            except GitHubInstallationRevoked:
                revoked_seen = True
                await _mark_installation_revoked(db, installation.id)
                continue
            except GitHubAccessLost:
                await _mark_repository_access(
                    db, installation.id, None, RepositoryAccessStatus.ACCESS_LOST
                )
                continue
            except GitHubRateLimited as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            except GitHubApiError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            metadata = next(
                (
                    repository
                    for repository in repositories
                    if repository.get("id") == payload.github_repo_id
                ),
                None,
            )
            if metadata is not None:
                selected_installation = installation
                break
        if selected_installation is None or metadata is None:
            raise HTTPException(
                status_code=401 if revoked_seen and len(installations) == 1 else 404,
                detail="Repository is not available to an active GitHub installation",
            )

        existing = await db.scalar(
            select(Repository).where(
                Repository.owner_id == current_user.id,
                Repository.github_installation_id == selected_installation.id,
                Repository.github_repo_id == payload.github_repo_id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Repository is already imported")
        selected_installation_id = selected_installation.id
        selected_installation_number = selected_installation.installation_id
        try:
            default_branch = metadata.get("default_branch") or await github_client.get_default_branch(
                selected_installation_number,
                payload.github_repo_id,
            )
            selected_branch = payload.branch or default_branch
            source = GitHubRepositorySource(
                github_client,
                selected_installation_number,
                payload.github_repo_id,
            )
            revision = await source.get_revision(selected_branch)
            return await _persist_repository(
                db,
                current_user,
                source,
                selected_branch,
                revision,
                metadata.get("name") or str(payload.github_repo_id),
                default_branch,
                selected_branch,
                selected_installation_id,
                payload.github_repo_id,
            )
        except GitHubInstallationRevoked as exc:
            await db.rollback()
            await _mark_installation_revoked(db, selected_installation_id)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except GitHubAccessLost as exc:
            await db.rollback()
            await _mark_repository_access(
                db,
                selected_installation_id,
                payload.github_repo_id,
                RepositoryAccessStatus.ACCESS_LOST,
            )
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except GitHubRepositoryDeleted as exc:
            await db.rollback()
            await _mark_repository_access(
                db,
                selected_installation_id,
                payload.github_repo_id,
                RepositoryAccessStatus.SOURCE_DELETED,
            )
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GitHubBranchMissing as exc:
            await db.rollback()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GitHubRateLimited as exc:
            await db.rollback()
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Repository is already imported") from exc
        except GitHubApiError as exc:
            await db.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    form = await request.form()
    upload = form.get("upload")
    if not isinstance(upload, StarletteUploadFile):
        raise HTTPException(status_code=400, detail="A ZIP archive is required")
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="A ZIP archive is required")

    with tempfile.TemporaryDirectory(prefix="prism-upload-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "upload.zip"
        extraction_root = temporary_root / "repository"
        await _save_upload(
            upload,
            archive_path,
            settings.max_zip_size_mb * 1024 * 1024,
        )
        try:
            safe_extract(archive_path, extraction_root)
        except ZipSafetyError as exc:
            response_status = 413 if exc.limit_exceeded else 400
            raise HTTPException(status_code=response_status, detail=exc.reason) from exc

        source = UploadedRepositorySource()
        revision = await source.get_revision(str(extraction_root))

        return await _persist_repository(
            db,
            current_user,
            source,
            str(extraction_root),
            revision,
            Path(upload.filename).stem,
            "upload",
            "upload",
        )
