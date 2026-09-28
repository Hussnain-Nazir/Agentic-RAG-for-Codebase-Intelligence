import asyncio
import io
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import create_access_token
from app.config import Settings, get_settings
from app.api.routes.repositories import get_embedding_provider
from app.db.base import Base
from app.db.session import get_db
from app.ingestion.pipeline import MVP_INDEXABLE_FILE_TARGET, SNIFF_BYTES, discover_and_normalize
from app.ingestion.security import ZipSafetyError, safe_extract
from app.sources.base import SourceFileRef
from app.main import create_app
from app.models import (
    CodeChunk,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    User,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEST_SECRET = "phase-five-test-secret-at-least-32-bytes"


class FakeEmbeddingProvider:
    dimensions = 384

    def __init__(self) -> None:
        self.call_count = 0
        self.embedded_texts: list[str] = []
        self.error: Exception | None = None

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.error is not None:
            raise self.error
        self.call_count += 1
        self.embedded_texts.extend(texts)
        return [[1.0, *([0.0] * 383)] for _ in texts]


def zip_entries(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.fixture
def ingestion_context() -> Iterator[
    tuple[TestClient, async_sessionmaker[AsyncSession], uuid.UUID, FakeEmbeddingProvider]
]:
    database_url = "sqlite+aiosqlite://"
    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email="upload@example.com",
                    hashed_password="unused",
                )
            )
            await session.commit()

    asyncio.run(prepare_database())

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_get_settings() -> Settings:
        return Settings(
            database_url=database_url,
            jwt_secret=TEST_SECRET,
            max_zip_size_mb=1,
        )

    app = create_app()
    embedding_provider = FakeEmbeddingProvider()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_embedding_provider] = lambda: embedding_provider
    with TestClient(app) as client:
        yield client, session_factory, user_id, embedding_provider
    asyncio.run(engine.dispose())


def auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(user_id, TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def test_zip_slip_is_rejected_before_outside_file_is_written() -> None:
    with TemporaryDirectory(prefix="prism-zip-slip-", dir=Path(__file__).parent) as temp:
        temporary_root = Path(temp)
        archive_path = temporary_root / "unsafe.zip"
        extraction_root = temporary_root / "extracted"
        outside = temporary_root / "escaped.py"
        archive_path.write_bytes(zip_entries({"../escaped.py": b"unsafe"}))

        with pytest.raises(ZipSafetyError, match="parent path segment"):
            safe_extract(archive_path, extraction_root)

        assert not outside.exists()
        assert not extraction_root.exists()


def test_normalization_skips_full_reads_for_oversized_and_binary_files() -> None:
    class ProbeSource:
        source_type = "upload"

        def __init__(self) -> None:
            self.prefix_reads: list[tuple[str, int]] = []
            self.full_reads: list[str] = []

        async def list_files(self, ref: str) -> list[SourceFileRef]:
            del ref
            return [
                SourceFileRef("large.py", 10**12),
                SourceFileRef("image.bin", 5),
                SourceFileRef("binary.txt", 5),
                SourceFileRef("main.py", 10),
            ]

        async def get_file_prefix(self, ref: str, path: str, max_bytes: int) -> bytes:
            del ref
            self.prefix_reads.append((path, max_bytes))
            return b"a\x00b" if path == "binary.txt" else b"value = 1\n"

        async def get_file_content(self, ref: str, path: str) -> bytes:
            del ref
            self.full_reads.append(path)
            return b"value = 1\n"

        async def get_revision(self, ref: str) -> str:
            del ref
            return "test-revision"

    source = ProbeSource()
    files = asyncio.run(discover_and_normalize(source, "test-revision"))
    by_path = {item.path: item for item in files}

    assert by_path["large.py"].status is RepositoryFileStatus.OVERSIZED
    assert by_path["image.bin"].status is RepositoryFileStatus.BINARY
    assert by_path["binary.txt"].status is RepositoryFileStatus.BINARY
    assert by_path["main.py"].status is RepositoryFileStatus.OK
    assert all(by_path[path].content_hash is None for path in ("large.py", "image.bin", "binary.txt"))
    assert source.prefix_reads == [("binary.txt", SNIFF_BYTES), ("main.py", SNIFF_BYTES)]
    assert source.full_reads == ["main.py"]


@pytest.mark.parametrize("error_type", [RuntimeError, NotImplementedError])
def test_zip_reader_errors_use_safe_rejection_path(
    error_type: type[Exception], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "archive.zip"
    archive_path.write_bytes(zip_entries({"app.py": b"value = 1\n"}))

    def fail_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise error_type("unsafe archive detail")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)
    with pytest.raises(ZipSafetyError, match="cannot be safely extracted"):
        safe_extract(archive_path, tmp_path / "extracted")


def test_oversized_zip_returns_413_before_extraction(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, user_id, _ = ingestion_context
    extraction_attempted = False

    def fail_if_called(*args: object, **kwargs: object) -> None:
        nonlocal extraction_attempted
        extraction_attempted = True

    monkeypatch.setattr(
        "app.api.routes.repositories.safe_extract",
        fail_if_called,
    )
    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={"upload": ("oversized.zip", b"x" * (1024 * 1024 + 1), "application/zip")},
    )

    assert response.status_code == 413
    assert extraction_attempted is False


def test_ignored_secret_and_binary_files_are_handled(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
) -> None:
    client, session_factory, user_id, _ = ingestion_context
    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={
            "upload": (
                "filtered.zip",
                (FIXTURES / "filtering_repo.zip").read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 201

    async def inspect() -> None:
        async with session_factory() as session:
            rows = list(await session.scalars(select(RepositoryFile)))
            by_path = {row.path: row.status for row in rows}
            assert by_path == {
                ".gitignore": RepositoryFileStatus.OK,
                "assets/blob.bin": RepositoryFileStatus.BINARY,
                "src/main.py": RepositoryFileStatus.OK,
            }

    asyncio.run(inspect())


def test_clean_fixture_normalizes_expected_repository_files(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
) -> None:
    client, session_factory, user_id, embedding_provider = ingestion_context
    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={
            "upload": (
                "clean.zip",
                (FIXTURES / "clean_repo.zip").read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["state"] == "READY"
    assert response.json()["size_warning"] is False

    async def inspect() -> None:
        async with session_factory() as session:
            rows = list(
                await session.scalars(
                    select(RepositoryFile).order_by(RepositoryFile.path)
                )
            )
            assert [row.path for row in rows] == ["README.md", "app.py"]
            assert all(row.status is RepositoryFileStatus.OK for row in rows)
            index = await session.scalar(select(RepositoryIndex))
            assert index is not None
            assert index.size_warning is False
            chunks = list(await session.scalars(select(CodeChunk)))
            assert chunks
            assert all(chunk.embedding is not None for chunk in chunks)
            assert all(chunk.embedding_model_version for chunk in chunks)

    assert embedding_provider.call_count == 1

    asyncio.run(inspect())


def test_embedding_failure_does_not_mark_repository_ready(ingestion_context) -> None:
    client, session_factory, user_id, provider = ingestion_context
    provider.error = RuntimeError("synthetic embedding failure")
    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={
            "upload": (
                "clean.zip",
                (FIXTURES / "clean_repo.zip").read_bytes(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 500

    async def index_state() -> str:
        async with session_factory() as session:
            index = await session.scalar(select(RepositoryIndex))
            assert index is not None
            return index.state.value

    assert asyncio.run(index_state()) == "FAILED"


def test_repository_over_mvp_target_is_ready_with_size_warning(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
) -> None:
    client, session_factory, user_id, _ = ingestion_context
    entries = {
        f"src/file_{number:04}.py": b"value = 1\n"
        for number in range(MVP_INDEXABLE_FILE_TARGET + 1)
    }
    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={"upload": ("large.zip", zip_entries(entries), "application/zip")},
    )

    assert response.status_code == 201
    assert response.json()["state"] == "READY"
    assert response.json()["size_warning"] is True

    async def inspect() -> None:
        async with session_factory() as session:
            index = await session.scalar(select(RepositoryIndex))
            assert index is not None
            assert index.state.value == "READY"
            assert index.size_warning is True
            assert index.files_processed == MVP_INDEXABLE_FILE_TARGET + 1

    asyncio.run(inspect())


def test_unchanged_reimport_reuses_embeddings_without_new_computation(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
) -> None:
    client, _, user_id, provider = ingestion_context
    payload = (FIXTURES / "clean_repo.zip").read_bytes()

    first = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={"upload": ("clean.zip", payload, "application/zip")},
    )
    calls_after_first = provider.call_count
    second = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={"upload": ("clean.zip", payload, "application/zip")},
    )

    assert first.status_code == second.status_code == 201
    assert calls_after_first == 1
    assert provider.call_count == calls_after_first


def test_embedding_failure_marks_index_failed(
    ingestion_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        FakeEmbeddingProvider,
    ],
) -> None:
    client, session_factory, user_id, provider = ingestion_context
    provider.error = RuntimeError("synthetic embedding failure")

    response = client.post(
        "/repositories",
        headers=auth_headers(user_id),
        files={
            "upload": (
                "clean.zip",
                (FIXTURES / "clean_repo.zip").read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Repository embedding failed"

    async def inspect() -> None:
        async with session_factory() as session:
            index = await session.scalar(select(RepositoryIndex))
            assert index is not None
            assert index.state is RepositoryIndexState.FAILED
            assert index.failure_reason is not None
            assert index.failure_reason == "Embedding failed: RuntimeError"

    asyncio.run(inspect())
