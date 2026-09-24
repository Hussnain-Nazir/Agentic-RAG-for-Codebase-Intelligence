import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.repositories import _persist_repository
from app.api.routes.github import get_github_client
from app.api.routes.repositories import get_embedding_provider
from app.auth.dependencies import get_current_user
from app.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.config import get_settings
from app.ingestion.sync import SyncInProgressError, synchronize_repository
from app.github.errors import (
    GitHubAccessLost,
    GitHubBranchMissing,
    GitHubInstallationRevoked,
    GitHubRateLimited,
    GitHubRepositoryDeleted,
)
from app.memory.service import MemoryService
from app.models import (
    CodeChunk,
    CodeRelationship,
    CodeSymbol,
    GitHubInstallation,
    GitHubInstallationStatus,
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryIndex,
    RepositoryIndexState,
    User,
)
from app.models.repository_memory import RepositoryMemorySource
from app.sources.github import GitHubRepositorySource
from app.main import create_app


class FakeGitHubClient:
    def __init__(self) -> None:
        self.revision = "revision-one"
        self.trees: dict[str, dict[str, tuple[str, bytes]]] = {
            self.revision: {
                "models.py": (
                    "sha-model-one",
                    b"def account_name(value: str) -> str:\n    return value\n",
                ),
                "service.py": (
                    "sha-service",
                    b"from models import account_name\n\ndef show_name(value: str) -> str:\n    return account_name(value)\n",
                ),
                "deleted.py": (
                    "sha-deleted",
                    b"def obsolete() -> str:\n    return 'old'\n",
                ),
            }
        }
        self.blob_calls: list[str] = []

    async def get_branch_revision(self, installation_id, repository_id, branch):
        assert (installation_id, repository_id, branch) == (77, 1001, "main")
        return self.revision

    async def get_repository_tree(self, installation_id, repository_id, revision):
        assert (installation_id, repository_id) == (77, 1001)
        return [
            {"type": "blob", "path": path, "sha": sha, "size": len(content)}
            for path, (sha, content) in self.trees[revision].items()
        ]

    async def get_blob_content(self, installation_id, repository_id, sha):
        assert (installation_id, repository_id) == (77, 1001)
        self.blob_calls.append(sha)
        return next(
            content
            for tree in self.trees.values()
            for _, (stored_sha, content) in tree.items()
            if stored_sha == sha
        )


class CountingEmbeddingProvider:
    dimensions = 384

    def __init__(self) -> None:
        self.calls = 0

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0, *([0.0] * 383)] for _ in texts]


@pytest_asyncio.fixture
async def sync_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    client = FakeGitHubClient()
    embedding = CountingEmbeddingProvider()
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret="phase-twenty-test-secret-at-least-32-bytes",
        embedding_model_name="fake-phase-20",
    )
    async with factory() as session:
        user = User(
            email=f"sync-{uuid.uuid4()}@example.com",
            hashed_password="unused",
        )
        session.add(user)
        await session.flush()
        installation = GitHubInstallation(
            user_id=user.id,
            installation_id=77,
            account_login="example",
        )
        session.add(installation)
        await session.flush()
        imported = await _persist_repository(
            session,
            user,
            GitHubRepositorySource(client, 77, 1001),
            "main",
            client.revision,
            "fixture",
            "main",
            "main",
            embedding,
            settings,
            installation.id,
            1001,
        )
        repository_id = uuid.UUID(imported.repository_id)
        index_id = uuid.UUID(imported.index_id)
    try:
        yield factory, client, embedding, settings, repository_id, index_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unchanged_sync_reuses_structure_and_embeddings(
    sync_context, monkeypatch
) -> None:
    factory, client, embedding, settings, repository_id, old_index_id = sync_context
    import app.ingestion.sync as sync_module

    original_parse = sync_module.parse_repository_files
    parse_calls = 0

    async def counted_parse(files):
        nonlocal parse_calls
        parse_calls += 1
        return await original_parse(files)

    monkeypatch.setattr(sync_module, "parse_repository_files", counted_parse)
    async with factory() as session:
        old_chunk = await session.scalar(
            select(CodeChunk).where(CodeChunk.repository_index_id == old_index_id)
        )
        assert old_chunk is not None
        memory = await MemoryService(session).save_repository_memory(
            repository_id,
            "FACT",
            "Stable repository fact.",
            [old_chunk.id],
            RepositoryMemorySource.EXPLICIT,
        )
        await session.commit()
        memory_id = memory.id
    embedding.calls = 0
    client.blob_calls.clear()
    async with factory() as session:
        index = await synchronize_repository(
            repository_id,
            session=session,
            github_client=client,
            embedding_provider=embedding,
            settings=settings,
        )
        assert index.version == 2
        assert index.state is RepositoryIndexState.READY
        old_chunks = list(
            await session.scalars(
                select(CodeChunk).where(CodeChunk.repository_index_id == old_index_id)
            )
        )
        new_chunks = list(
            await session.scalars(
                select(CodeChunk).where(CodeChunk.repository_index_id == index.id)
            )
        )
        assert {item.content_hash for item in new_chunks} == {
            item.content_hash for item in old_chunks
        }
        assert all(item.embedding is not None for item in new_chunks)
        assert {item.id for item in old_chunks}.isdisjoint(
            {item.id for item in new_chunks}
        )
        migrated_memory = await session.get(type(memory), memory_id)
        assert migrated_memory is not None
        assert not migrated_memory.is_stale
        assert migrated_memory.repository_index_version == 2
        assert set(migrated_memory.evidence_ids) <= {
            str(item.id) for item in new_chunks
        }
    assert parse_calls == 0
    assert embedding.calls == 0
    assert client.blob_calls == []


@pytest.mark.asyncio
async def test_changed_new_deleted_sync_rebuilds_and_stales_memory(sync_context) -> None:
    factory, client, embedding, settings, repository_id, old_index_id = sync_context
    async with factory() as session:
        old_model_chunk = await session.scalar(
            select(CodeChunk).where(
                CodeChunk.repository_index_id == old_index_id,
                CodeChunk.file_path == "models.py",
            )
        )
        assert old_model_chunk is not None
        memory = await MemoryService(session).save_repository_memory(
            repository_id,
            "FACT",
            "Account naming uses the old implementation.",
            [old_model_chunk.id],
            RepositoryMemorySource.EXPLICIT,
        )
        await session.commit()
        memory_id = memory.id

    client.revision = "revision-two"
    client.trees[client.revision] = {
        "models.py": (
            "sha-model-two",
            b"def account_name(value: str) -> str:\n    return value.upper()\n",
        ),
        "service.py": client.trees["revision-one"]["service.py"],
        "new.py": (
            "sha-new",
            b"def recently_added() -> str:\n    return account_name('new')\n",
        ),
    }
    embedding.calls = 0
    client.blob_calls.clear()
    async with factory() as session:
        index = await synchronize_repository(
            repository_id,
            session=session,
            github_client=client,
            embedding_provider=embedding,
            settings=settings,
        )
        assert index.version == 2
        assert index.state is RepositoryIndexState.READY
        files = list(
            await session.scalars(
                select(RepositoryFile).where(RepositoryFile.repository_index_id == index.id)
            )
        )
        assert {item.path for item in files} == {"models.py", "service.py", "new.py"}
        symbols = list(
            await session.scalars(
                select(CodeSymbol).where(CodeSymbol.repository_index_id == index.id)
            )
        )
        assert {item.name for item in symbols} >= {
            "account_name", "show_name", "recently_added"
        }
        assert "obsolete" not in {item.name for item in symbols}
        chunks = list(
            await session.scalars(
                select(CodeChunk).where(CodeChunk.repository_index_id == index.id)
            )
        )
        old_model_chunks = list(
            await session.scalars(
                select(CodeChunk).where(
                    CodeChunk.repository_index_id == old_index_id,
                    CodeChunk.file_path == "models.py",
                )
            )
        )
        new_model_chunks = [
            item for item in chunks if item.file_path == "models.py"
        ]
        assert {item.id for item in old_model_chunks}.isdisjoint(
            {item.id for item in new_model_chunks}
        )
        assert {item.content_hash for item in old_model_chunks} != {
            item.content_hash for item in new_model_chunks
        }
        old_model_symbols = list(
            await session.scalars(
                select(CodeSymbol).where(
                    CodeSymbol.repository_index_id == old_index_id,
                    CodeSymbol.name == "account_name",
                )
            )
        )
        assert {item.id for item in old_model_symbols}.isdisjoint(
            {item.id for item in symbols if item.name == "account_name"}
        )
        assert all(item.file_path != "deleted.py" for item in chunks)
        assert any("return value.upper()" in item.content for item in chunks)
        relationships = list(
            await session.scalars(
                select(CodeRelationship).where(
                    CodeRelationship.repository_index_id == index.id
                )
            )
        )
        names = {item.id: item.name for item in symbols}
        assert all(
            names.get(item.from_symbol_id) != "obsolete"
            and names.get(item.to_symbol_id) != "obsolete"
            for item in relationships
        )
        assert any(
            names.get(item.from_symbol_id) == "show_name"
            and names.get(item.to_symbol_id) == "account_name"
            for item in relationships
        )
        refreshed_memory = await session.get(type(memory), memory_id)
        assert refreshed_memory is not None
        assert refreshed_memory.is_stale
    assert set(client.blob_calls) == {"sha-model-two", "sha-new"}
    assert embedding.calls >= 1


@pytest.mark.asyncio
async def test_existing_active_index_rejects_sync(sync_context) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    async with factory() as session:
        session.add(
            RepositoryIndex(
                repository_id=repository_id,
                version=2,
                revision="in-progress",
                state=RepositoryIndexState.PARSING,
            )
        )
        await session.commit()
        with pytest.raises(SyncInProgressError):
            await synchronize_repository(
                repository_id,
                session=session,
                github_client=client,
                embedding_provider=embedding,
                settings=settings,
            )


@pytest.mark.asyncio
async def test_changed_sha_with_identical_content_reuses_embedding(sync_context) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    client.revision = "revision-identical-content"
    client.trees[client.revision] = {
        **client.trees["revision-one"],
        "models.py": (
            "new-blob-sha-for-same-content",
            client.trees["revision-one"]["models.py"][1],
        ),
    }
    embedding.calls = 0
    client.blob_calls.clear()
    async with factory() as session:
        index = await synchronize_repository(
            repository_id,
            session=session,
            github_client=client,
            embedding_provider=embedding,
            settings=settings,
        )
        assert index.state is RepositoryIndexState.READY
    assert client.blob_calls == ["new-blob-sha-for-same-content"]
    assert embedding.calls == 0


@pytest.mark.asyncio
async def test_failed_sync_marks_new_index_failed_without_expired_attribute_access(
    sync_context,
) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    client.revision = "missing-tree"

    async with factory() as session:
        with pytest.raises(KeyError):
            await synchronize_repository(
                repository_id,
                session=session,
                github_client=client,
                embedding_provider=embedding,
                settings=settings,
            )
        failed = await session.scalar(
            select(RepositoryIndex).where(
                RepositoryIndex.repository_id == repository_id,
                RepositoryIndex.version == 2,
            )
        )
        assert failed is not None
        assert failed.state is RepositoryIndexState.FAILED
        assert failed.failure_reason == "Synchronization failed: KeyError"


@pytest.mark.asyncio
async def test_sync_endpoint_rejects_active_job_with_409(sync_context) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    async with factory() as session:
        user = await session.scalar(select(User))
        assert user is not None
        session.add(
            RepositoryIndex(
                repository_id=repository_id,
                version=2,
                revision="in-progress",
                state=RepositoryIndexState.PARSING,
            )
        )
        await session.commit()

    async def override_db() -> AsyncIterator:
        async with factory() as session:
            yield session

    async def override_user():
        return user

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_github_client] = lambda: client
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post(f"/repositories/{repository_id}/sync")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_sync_endpoint_rejects_other_owner(sync_context) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    async with factory() as session:
        other = User(
            email=f"other-{uuid.uuid4()}@example.com",
            hashed_password="unused",
        )
        session.add(other)
        await session.commit()

    async def override_db() -> AsyncIterator:
        async with factory() as session:
            yield session

    async def override_user():
        return other

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_github_client] = lambda: client
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post(f"/repositories/{repository_id}/sync")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_sync_endpoint_returns_new_index(sync_context) -> None:
    factory, client, embedding, settings, repository_id, old_index_id = sync_context
    async with factory() as session:
        user = await session.scalar(select(User))
        assert user is not None

    async def override_db() -> AsyncIterator:
        async with factory() as session:
            yield session

    async def override_user():
        return user

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_github_client] = lambda: client
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post(f"/repositories/{repository_id}/sync")
    assert response.status_code == 200
    assert response.json()["state"] == "READY"
    assert uuid.UUID(response.json()["index_id"]) != old_index_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_status", "expected_access"),
    [
        (GitHubInstallationRevoked, 401, RepositoryAccessStatus.ACCESS_LOST),
        (GitHubAccessLost, 403, RepositoryAccessStatus.ACCESS_LOST),
        (GitHubRepositoryDeleted, 404, RepositoryAccessStatus.SOURCE_DELETED),
        (GitHubBranchMissing, 404, RepositoryAccessStatus.ACTIVE),
        (GitHubRateLimited, 429, RepositoryAccessStatus.ACTIVE),
    ],
)
async def test_sync_endpoint_maps_typed_github_lifecycle_errors(
    sync_context, monkeypatch, error_type, expected_status, expected_access
) -> None:
    factory, client, embedding, settings, repository_id, _ = sync_context
    async with factory() as session:
        user = await session.scalar(select(User))
        assert user is not None

    async def fail_revision(installation_id, github_repo_id, branch):
        del installation_id, github_repo_id, branch
        raise error_type("GitHub source unavailable")

    monkeypatch.setattr(client, "get_branch_revision", fail_revision)

    async def override_db() -> AsyncIterator:
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_github_client] = lambda: client
    app.dependency_overrides[get_embedding_provider] = lambda: embedding
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post(f"/repositories/{repository_id}/sync")
    assert response.status_code == expected_status

    async with factory() as session:
        repository = await session.get(Repository, repository_id)
        installation = await session.scalar(select(GitHubInstallation))
        assert repository is not None and repository.access_status is expected_access
        assert installation is not None
        assert installation.status is (
            GitHubInstallationStatus.REVOKED
            if error_type is GitHubInstallationRevoked
            else GitHubInstallationStatus.ACTIVE
        )
