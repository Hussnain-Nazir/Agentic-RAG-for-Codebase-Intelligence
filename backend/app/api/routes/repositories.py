import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.ingestion.pipeline import discover_and_normalize, exceeds_mvp_file_target
from app.ingestion.security import ZipSafetyError, safe_extract
from app.models.repository import (
    Repository,
    RepositoryAccessStatus,
    RepositorySourceType,
)
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.models.user import User
from app.sources.upload import UploadedRepositorySource

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryUploadResponse(BaseModel):
    repository_id: str
    index_id: str
    state: RepositoryIndexState
    size_warning: bool


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


@router.post("", response_model=RepositoryUploadResponse, status_code=201)
async def upload_repository(
    upload: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RepositoryUploadResponse:
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

        repository = Repository(
            owner_id=current_user.id,
            source_type=RepositorySourceType.UPLOAD,
            name=Path(upload.filename).stem,
            default_branch="upload",
            selected_branch="upload",
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
        normalized = await discover_and_normalize(source, str(extraction_root))
        repository_index.files_discovered = len(normalized)
        repository_index.files_processed = sum(
            item.status is RepositoryFileStatus.OK for item in normalized
        )
        repository_index.size_warning = exceeds_mvp_file_target(normalized)
        for item in normalized:
            db.add(
                RepositoryFile(
                    repository_index_id=repository_index.id,
                    path=item.path,
                    language=item.language,
                    github_sha=item.github_sha,
                    content_hash=item.content_hash,
                    status=item.status,
                    size_bytes=item.size_bytes,
                )
            )
        repository_index.state = RepositoryIndexState.READY
        await db.commit()

        return RepositoryUploadResponse(
            repository_id=str(repository.id),
            index_id=str(repository_index.id),
            state=repository_index.state,
            size_warning=repository_index.size_warning,
        )
