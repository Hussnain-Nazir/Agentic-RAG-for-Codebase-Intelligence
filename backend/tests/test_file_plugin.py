import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.plugins.file_reading.errors import (
    BinaryFileError,
    FileTooLargeError,
    LineRangeError,
    PathTraversalError,
    UnauthorizedRepositoryAccessError,
    UnsupportedFileTypeError,
)
from app.plugins.file_reading.tool import (
    ReadFileInput,
    ReadFileRangeInput,
    ReadFileRangeTool,
    ReadFileTool,
)
from app.tools.base import ExecutionContext


@pytest_asyncio.fixture
async def file_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        user = User(email="file-plugin@example.com", hashed_password="unused")
        repository = Repository(
            owner=user,
            source_type=RepositorySourceType.UPLOAD,
            name="file-plugin",
            default_branch="upload",
            selected_branch="upload",
            access_status=RepositoryAccessStatus.ACTIVE,
        )
        session.add(repository)
        await session.flush()
        index = RepositoryIndex(
            repository_id=repository.id,
            version=1,
            revision="file-plugin",
            state=RepositoryIndexState.READY,
        )
        session.add(index)
        await session.flush()
        files = [
            RepositoryFile(
                repository_index_id=index.id,
                path="src/app.py",
                language="python",
                content_hash="a" * 64,
                status=RepositoryFileStatus.OK,
                size_bytes=17,
                content="first\nsecond\nthird\n",
            ),
            RepositoryFile(
                repository_index_id=index.id,
                path="bin/tool.exe",
                language=None,
                content_hash="b" * 64,
                status=RepositoryFileStatus.OK,
                size_bytes=4,
                content="tool",
            ),
            RepositoryFile(
                repository_index_id=index.id,
                path="data/binary.txt",
                language="documentation",
                content_hash="c" * 64,
                status=RepositoryFileStatus.BINARY,
                size_bytes=4,
                content=None,
            ),
            RepositoryFile(
                repository_index_id=index.id,
                path="data/large.txt",
                language="documentation",
                content_hash="d" * 64,
                status=RepositoryFileStatus.OVERSIZED,
                size_bytes=2_000_000,
                content=None,
            ),
            RepositoryFile(
                repository_index_id=index.id,
                path="docs/guide.pdf",
                language=None,
                content_hash=None,
                status=RepositoryFileStatus.BINARY,
                size_bytes=20,
                content=None,
            ),
        ]
        session.add_all(files)
        await session.flush()
        yield session, repository, user
    await engine.dispose()


@pytest.mark.asyncio
async def test_valid_file_and_range_reads_return_exact_content(file_context) -> None:
    session, repository, user = file_context
    ctx = ExecutionContext(repository_id=repository.id, user_id=user.id)

    whole = await ReadFileTool(session).execute(
        ReadFileInput(repository_id=repository.id, path="src/app.py"), ctx
    )
    ranged = await ReadFileRangeTool(session).execute(
        ReadFileRangeInput(
            repository_id=repository.id,
            path="src/app.py",
            start_line=2,
            end_line=3,
        ),
        ctx,
    )

    assert whole.content == "first\nsecond\nthird\n"
    assert whole.start_line == 1
    assert whole.end_line == whole.total_lines == 3
    assert whole.truncated is False
    assert ranged.content == "second\nthird\n"
    assert (ranged.start_line, ranged.end_line) == (2, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("../secret.py", PathTraversalError),
        ("C:\\secret.py", PathTraversalError),
        ("bin/tool.exe", UnsupportedFileTypeError),
        ("data/binary.txt", BinaryFileError),
        ("data/large.txt", FileTooLargeError),
        ("docs/guide.pdf", UnsupportedFileTypeError),
    ],
)
async def test_invalid_file_reads_raise_specific_errors(
    file_context, path: str, error: type[Exception]
) -> None:
    session, repository, user = file_context
    ctx = ExecutionContext(repository_id=repository.id, user_id=user.id)

    with pytest.raises(error):
        await ReadFileTool(session).execute(
            ReadFileInput(repository_id=repository.id, path=path), ctx
        )


@pytest.mark.asyncio
async def test_out_of_range_lines_are_rejected(file_context) -> None:
    session, repository, user = file_context
    ctx = ExecutionContext(repository_id=repository.id, user_id=user.id)

    with pytest.raises(LineRangeError):
        await ReadFileRangeTool(session).execute(
            ReadFileRangeInput(
                repository_id=repository.id,
                path="src/app.py",
                start_line=2,
                end_line=4,
            ),
            ctx,
        )


@pytest.mark.asyncio
async def test_repository_access_is_checked_before_path(file_context) -> None:
    session, repository, _ = file_context

    with pytest.raises(UnauthorizedRepositoryAccessError):
        await ReadFileTool(session).execute(
            ReadFileInput(repository_id=repository.id, path="../secret.py"),
            ExecutionContext(repository_id=repository.id, user_id=uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_read_file_truncates_after_four_thousand_lines(file_context) -> None:
    session, repository, user = file_context
    index = await session.scalar(
        select(RepositoryIndex).where(RepositoryIndex.repository_id == repository.id)
    )
    assert index is not None
    content = "".join(f"line {number}\n" for number in range(1, 4_002))
    session.add(
        RepositoryFile(
            repository_index_id=index.id,
            path="src/long.py",
            language="python",
            content_hash="e" * 64,
            status=RepositoryFileStatus.OK,
            size_bytes=len(content),
            content=content,
        )
    )
    await session.flush()

    result = await ReadFileTool(session).execute(
        ReadFileInput(repository_id=repository.id, path="src/long.py"),
        ExecutionContext(repository_id=repository.id, user_id=user.id),
    )

    assert result.truncated is True
    assert result.end_line == 4_000
    assert result.total_lines == 4_001
    assert result.content.endswith("line 4000\n")
