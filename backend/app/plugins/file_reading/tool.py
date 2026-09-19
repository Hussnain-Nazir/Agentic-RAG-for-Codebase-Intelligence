import ntpath
import uuid
from pathlib import PurePosixPath

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.plugins.file_reading.errors import (
    BinaryFileError,
    FileTooLargeError,
    IndexNotReadyError,
    LineRangeError,
    PathTraversalError,
    RepositoryFileNotFoundError,
    RepositoryNotFoundError,
    UnauthorizedRepositoryAccessError,
    UnsupportedFileTypeError,
)
from app.tools.base import ExecutionContext
from app.tools.repository_context import authorize_repository, current_repository_index

SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
}
MAX_READ_LINES = 4_000


class ReadFileInput(BaseModel):
    repository_id: uuid.UUID
    path: str


class ReadFileRangeInput(ReadFileInput):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class FileContent(BaseModel):
    path: str
    language: str | None
    content: str
    start_line: int
    end_line: int
    total_lines: int
    truncated: bool


def _normalize_path(path: str) -> str:
    value = path.replace("\\", "/")
    normalized = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or ntpath.splitdrive(value)[0]
        or ".." in normalized.parts
        or normalized.is_absolute()
    ):
        raise PathTraversalError("Repository path must be relative and cannot contain '..'")
    return normalized.as_posix()


async def _current_file(
    session: AsyncSession,
    repository_id: uuid.UUID,
    path: str,
) -> RepositoryFile:
    current_index = await current_repository_index(session, repository_id)
    repository_file = await session.scalar(
        select(RepositoryFile).where(
            RepositoryFile.repository_index_id == current_index.id,
            RepositoryFile.path == path,
        )
    )
    if repository_file is None:
        raise RepositoryFileNotFoundError("File does not exist in the current index")
    return repository_file


async def _stored_content(session: AsyncSession, file: RepositoryFile) -> str:
    if file.content is not None:
        return file.content
    chunks = list(
        await session.scalars(
            select(CodeChunk)
            .where(CodeChunk.file_id == file.id)
            .order_by(CodeChunk.start_line, CodeChunk.end_line, CodeChunk.id)
        )
    )
    return "\n".join(chunk.content for chunk in chunks)


async def _validated_file(
    session: AsyncSession,
    repository_id: uuid.UUID,
    path: str,
    ctx: ExecutionContext,
) -> tuple[RepositoryFile, str, str]:
    # The validation order below is a security contract from PRISM_SPEC.md 18.1.
    await authorize_repository(session, repository_id, ctx)
    normalized = _normalize_path(path)
    repository_file = await _current_file(session, repository_id, normalized)
    if PurePosixPath(normalized).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError("Unsupported file type")
    if repository_file.status is RepositoryFileStatus.BINARY:
        raise BinaryFileError("Binary files cannot be read")
    if repository_file.status is RepositoryFileStatus.OVERSIZED:
        raise FileTooLargeError("File exceeds the configured size limit")
    content = await _stored_content(session, repository_file)
    return repository_file, normalized, content


def _lines(content: str) -> list[str]:
    return content.splitlines(keepends=True)


async def read_file(
    session: AsyncSession,
    input: ReadFileInput,
    ctx: ExecutionContext,
) -> FileContent:
    repository_file, normalized, content = await _validated_file(
        session, input.repository_id, input.path, ctx
    )
    lines = _lines(content)
    selected = lines[:MAX_READ_LINES]
    return FileContent(
        path=normalized,
        language=repository_file.language,
        content="".join(selected),
        start_line=1,
        end_line=len(selected),
        total_lines=len(lines),
        truncated=len(lines) > MAX_READ_LINES,
    )


async def read_file_range(
    session: AsyncSession,
    input: ReadFileRangeInput,
    ctx: ExecutionContext,
) -> FileContent:
    repository_file, normalized, content = await _validated_file(
        session, input.repository_id, input.path, ctx
    )
    lines = _lines(content)
    if input.end_line < input.start_line or input.end_line > len(lines):
        raise LineRangeError("Requested line range is outside the file")
    selected = lines[input.start_line - 1 : input.end_line]
    return FileContent(
        path=normalized,
        language=repository_file.language,
        content="".join(selected),
        start_line=input.start_line,
        end_line=input.end_line,
        total_lines=len(lines),
        truncated=False,
    )


class ReadFileTool:
    name = "read_file"
    description = "Read a supported file from the current stored repository index."
    input_schema = ReadFileInput
    output_schema = FileContent
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        return await read_file(self._session, ReadFileInput.model_validate(input), ctx)


class ReadFileRangeTool:
    name = "read_file_range"
    description = "Read an inclusive line range from a stored repository file."
    input_schema = ReadFileRangeInput
    output_schema = FileContent
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        return await read_file_range(
            self._session,
            ReadFileRangeInput.model_validate(input),
            ctx,
        )
