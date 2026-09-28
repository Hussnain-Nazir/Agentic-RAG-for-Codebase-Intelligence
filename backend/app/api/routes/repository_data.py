import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repository_or_404
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.memory.service import MemoryService
from app.models.code_chunk import CodeChunk
from app.models.finding import Finding, FindingType
from app.models.repository import Repository, RepositoryAccessStatus, RepositorySourceType
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.models.repository_memory import (
    RepositoryMemoryConfidence,
    RepositoryMemorySource,
    RepositoryMemoryType,
)
from app.models.user import User
from app.plugins.file_reading.errors import (
    BinaryFileError,
    FileTooLargeError,
    IndexNotReadyError,
    LineRangeError,
    PathTraversalError,
    RepositoryFileNotFoundError,
    UnsupportedFileTypeError,
)
from app.plugins.file_reading.tool import (
    FileContent,
    ReadFileInput,
    ReadFileRangeInput,
    _normalize_path,
    read_file,
    read_file_range,
)
from app.tools.base import ExecutionContext
from app.tools.errors import IndexNotReadyError as ToolIndexNotReadyError
from app.tools.repository_context import current_repository_index
from app.tools.repository_tools import FindSymbolTool
from app.tools.schemas import CodeSymbolResult, FindSymbolInput


router = APIRouter(prefix="/repositories", tags=["repositories"])


class IndexSummary(BaseModel):
    id: uuid.UUID
    version: int
    revision: str
    state: RepositoryIndexState
    files_discovered: int
    files_processed: int
    files_failed: int
    size_warning: bool
    failure_reason: str | None


class RepositorySummary(BaseModel):
    id: uuid.UUID
    name: str
    source_type: RepositorySourceType
    selected_branch: str
    access_status: RepositoryAccessStatus
    index: IndexSummary | None


class RepositoryDetail(RepositorySummary):
    owner_id: uuid.UUID
    github_repo_id: int | None
    default_branch: str
    created_at: datetime


class IndexStatus(BaseModel):
    index_id: uuid.UUID
    version: int
    state: RepositoryIndexState
    files_discovered: int
    files_processed: int
    files_failed: int
    size_warning: bool
    failure_reason: str | None


class FileTreeEntry(BaseModel):
    path: str
    name: str
    is_directory: bool
    language: str | None = None
    status: RepositoryFileStatus | None = None
    size_bytes: int | None = None


class RepositoryMemoryResponse(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    repository_index_version: int
    type: RepositoryMemoryType
    scope: str
    topic: str
    content: str
    evidence_ids: list[uuid.UUID]
    confidence: RepositoryMemoryConfidence
    is_stale: bool
    source: RepositoryMemorySource
    created_at: datetime
    updated_at: datetime


class SaveFindingRequest(BaseModel):
    type: FindingType
    content: dict[str, Any]
    evidence_ids: list[uuid.UUID] = Field(min_length=1)


class FindingResponse(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    session_id: uuid.UUID | None
    type: FindingType
    title: str
    content: dict[str, Any]
    evidence_ids: list[uuid.UUID]
    created_at: datetime


class ResolvedEvidenceLink(BaseModel):
    evidence_id: uuid.UUID
    file_path: str | None
    start_line: int | None
    end_line: int | None
    content_excerpt: str | None


def _index_summary(index: RepositoryIndex | None) -> IndexSummary | None:
    if index is None:
        return None
    return IndexSummary(
        id=index.id,
        version=index.version,
        revision=index.revision,
        state=index.state,
        files_discovered=index.files_discovered,
        files_processed=index.files_processed,
        files_failed=index.files_failed,
        size_warning=index.size_warning,
        failure_reason=index.failure_reason,
    )


async def _latest_index(
    db: AsyncSession, repository_id: uuid.UUID
) -> RepositoryIndex | None:
    return await db.scalar(
        select(RepositoryIndex)
        .where(RepositoryIndex.repository_id == repository_id)
        .order_by(RepositoryIndex.version.desc())
        .limit(1)
    )


def _summary(repository: Repository, index: RepositoryIndex | None) -> RepositorySummary:
    return RepositorySummary(
        id=repository.id,
        name=repository.name,
        source_type=repository.source_type,
        selected_branch=repository.selected_branch,
        access_status=repository.access_status,
        index=_index_summary(index),
    )


@router.get("", response_model=list[RepositorySummary])
async def list_repositories(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[RepositorySummary]:
    repositories = list(await db.scalars(
        select(Repository)
        .where(Repository.owner_id == current_user.id)
        .order_by(Repository.created_at.desc(), Repository.id)
    ))
    if not repositories:
        return []
    indexes = list(await db.scalars(
        select(RepositoryIndex)
        .where(RepositoryIndex.repository_id.in_([item.id for item in repositories]))
        .order_by(RepositoryIndex.repository_id, RepositoryIndex.version.desc())
    ))
    latest: dict[uuid.UUID, RepositoryIndex] = {}
    for index in indexes:
        latest.setdefault(index.repository_id, index)
    return [_summary(item, latest.get(item.id)) for item in repositories]


@router.get("/{repository_id}", response_model=RepositoryDetail)
async def get_repository(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
) -> RepositoryDetail:
    summary = _summary(repository, await _latest_index(db, repository_id))
    return RepositoryDetail(
        **summary.model_dump(),
        owner_id=repository.owner_id,
        github_repo_id=repository.github_repo_id,
        default_branch=repository.default_branch,
        created_at=repository.created_at,
    )


@router.get("/{repository_id}/index-status", response_model=IndexStatus)
async def get_index_status(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
) -> IndexStatus:
    del repository
    index = await _latest_index(db, repository_id)
    if index is None:
        raise HTTPException(status_code=404, detail="Repository index not found")
    return IndexStatus(
        index_id=index.id,
        version=index.version,
        state=index.state,
        files_discovered=index.files_discovered,
        files_processed=index.files_processed,
        files_failed=index.files_failed,
        size_warning=index.size_warning,
        failure_reason=index.failure_reason,
    )


@router.get("/{repository_id}/files", response_model=list[FileTreeEntry])
async def browse_files(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    path: str = "",
) -> list[FileTreeEntry]:
    del repository
    try:
        scope = _normalize_path(path) if path else ""
    except PathTraversalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        index = await current_repository_index(db, repository_id)
    except ToolIndexNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    statement = select(RepositoryFile).where(
        RepositoryFile.repository_index_id == index.id
    )
    files = list(await db.scalars(statement.order_by(RepositoryFile.path)))
    if scope:
        files = [file for file in files if file.path.startswith(f"{scope}/")]
    if scope and not files:
        raise HTTPException(status_code=404, detail="Directory not found")
    entries: dict[str, FileTreeEntry] = {}
    for file in files:
        suffix = file.path[len(scope) + 1:] if scope else file.path
        first, _, remainder = suffix.partition("/")
        child_path = f"{scope}/{first}" if scope else first
        if remainder:
            entries[child_path] = FileTreeEntry(
                path=child_path, name=first, is_directory=True
            )
        elif child_path not in entries:
            entries[child_path] = FileTreeEntry(
                path=child_path,
                name=first,
                is_directory=False,
                language=file.language,
                status=file.status,
                size_bytes=file.size_bytes,
            )
    return [entries[key] for key in sorted(entries)]


@router.get("/{repository_id}/files/content", response_model=FileContent)
async def get_file_content(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    path: Annotated[str, Query(min_length=1)],
    start_line: int | None = None,
    end_line: int | None = None,
) -> FileContent:
    del repository
    ctx = ExecutionContext(repository_id=repository_id, user_id=current_user.id)
    if (start_line is None) != (end_line is None):
        raise HTTPException(status_code=400, detail="Both start_line and end_line are required")
    if start_line is not None and (start_line < 1 or end_line < 1):
        raise HTTPException(status_code=400, detail="Line numbers must be positive")
    try:
        if start_line is None:
            return await read_file(db, ReadFileInput(repository_id=repository_id, path=path), ctx)
        return await read_file_range(
            db,
            ReadFileRangeInput(
                repository_id=repository_id,
                path=path,
                start_line=start_line,
                end_line=end_line,
            ),
            ctx,
        )
    except RepositoryFileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PathTraversalError, UnsupportedFileTypeError, BinaryFileError, LineRangeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except IndexNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{repository_id}/symbols", response_model=list[CodeSymbolResult])
async def list_symbols(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    q: Annotated[str, Query(min_length=1)],
) -> list[CodeSymbolResult]:
    del repository
    try:
        result = await FindSymbolTool(db).execute(
            FindSymbolInput(repository_id=repository_id, symbol_name=q),
            ExecutionContext(repository_id=repository_id, user_id=current_user.id),
        )
    except ToolIndexNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.root


@router.get("/{repository_id}/memory", response_model=list[RepositoryMemoryResponse])
async def list_repository_memory(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    include_stale: bool = False,
) -> list[RepositoryMemoryResponse]:
    del repository
    memories = await MemoryService(db).retrieve_repository_memory(
        repository_id, "", include_stale=include_stale
    )
    return [RepositoryMemoryResponse.model_validate(item, from_attributes=True) for item in memories]


@router.get("/{repository_id}/evidence", response_model=list[ResolvedEvidenceLink])
async def resolve_evidence_links(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    ids: Annotated[list[uuid.UUID], Query(min_length=1, max_length=100)],
) -> list[ResolvedEvidenceLink]:
    del repository
    try:
        index = await current_repository_index(db, repository_id)
    except ToolIndexNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    chunks = list(await db.scalars(select(CodeChunk).where(
        CodeChunk.repository_id == repository_id,
        CodeChunk.repository_index_id == index.id,
        CodeChunk.id.in_(ids),
    )))
    by_id = {chunk.id: chunk for chunk in chunks}
    return [
        ResolvedEvidenceLink(
            evidence_id=evidence_id,
            file_path=by_id[evidence_id].file_path if evidence_id in by_id else None,
            start_line=by_id[evidence_id].start_line if evidence_id in by_id else None,
            end_line=by_id[evidence_id].end_line if evidence_id in by_id else None,
            content_excerpt=by_id[evidence_id].content[:500] if evidence_id in by_id else None,
        )
        for evidence_id in ids
    ]


@router.post(
    "/{repository_id}/findings",
    response_model=FindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_finding(
    repository_id: uuid.UUID,
    request: SaveFindingRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
) -> FindingResponse:
    del repository
    try:
        finding = await MemoryService(db).save_finding(
            repository_id,
            request.type,
            request.content,
            request.evidence_ids,
            session_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return FindingResponse.model_validate(finding, from_attributes=True)


@router.get("/{repository_id}/findings", response_model=list[FindingResponse])
async def list_findings(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
) -> list[FindingResponse]:
    del repository
    findings = list(await db.scalars(
        select(Finding)
        .where(Finding.repository_id == repository_id)
        .order_by(Finding.created_at.desc(), Finding.id)
    ))
    return [FindingResponse.model_validate(item, from_attributes=True) for item in findings]


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repository_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
) -> None:
    del repository
    await db.execute(delete(Repository).where(Repository.id == repository_id))
    await db.commit()
