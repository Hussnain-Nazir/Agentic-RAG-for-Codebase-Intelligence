import hashlib
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.embeddings.base import EmbeddingProvider
from app.embeddings.local_provider import LocalEmbeddingProvider
from app.ingestion.embedding_stage import (
    current_embedding_model_version,
    embed_repository_chunks,
)
from app.models import (
    CodeChunk,
    CodeChunkType,
    Repository,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.retrieval.vector_search import semantic_search


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 382)]


class FakeEmbeddingProvider:
    dimensions = 384

    def __init__(self) -> None:
        self.call_count = 0
        self.embedded_texts: list[str] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.embedded_texts.extend(texts)
        return [vector(1.0) if "auth" in text else vector(0.0, 1.0) for text in texts]


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.batch_lengths: list[int] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 384

    def encode(self, texts: list[str], **kwargs) -> list[list[float]]:
        assert kwargs["batch_size"] == 32
        assert kwargs["normalize_embeddings"] is True
        self.batch_lengths.append(len(texts))
        return [vector(1.0) for _ in texts]


def assert_provider_protocol(provider: EmbeddingProvider) -> EmbeddingProvider:
    return provider


async def make_repository(session, email: str, version: int = 1):
    user = User(email=email, hashed_password="unused")
    session.add(user)
    await session.flush()
    repository = Repository(
        owner_id=user.id,
        source_type=RepositorySourceType.UPLOAD,
        name=email,
        default_branch="upload",
        selected_branch="upload",
    )
    session.add(repository)
    await session.flush()
    repository_index = RepositoryIndex(
        repository_id=repository.id,
        version=version,
        revision=f"fixture-{version}",
        state=RepositoryIndexState.EMBEDDING,
    )
    session.add(repository_index)
    await session.flush()
    repository_file = RepositoryFile(
        repository_index_id=repository_index.id,
        path="fixture.py",
        language="python",
        content_hash="f" * 64,
        status=RepositoryFileStatus.OK,
        size_bytes=10,
        content="fixture",
    )
    session.add(repository_file)
    await session.flush()
    return repository, repository_index, repository_file


def make_chunk(repository, repository_index, repository_file, content: str) -> CodeChunk:
    return CodeChunk(
        repository_id=repository.id,
        repository_index_id=repository_index.id,
        file_id=repository_file.id,
        file_path=repository_file.path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name=None,
        symbol_type=None,
        parent_symbol=None,
        start_line=1,
        end_line=1,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        embedding=None,
        embedding_model_version=None,
        chunk_metadata={"source_type": "CODE"},
    )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_local_provider_calls_model_in_batches_of_32() -> None:
    model = FakeSentenceTransformer()
    provider = LocalEmbeddingProvider(model=model)

    results = await provider.embed_batch([str(number) for number in range(65)])

    assert len(results) == 65
    assert model.batch_lengths == [32, 32, 1]


@pytest.mark.asyncio
async def test_duplicate_embeddings_are_reused_and_rerun_computes_nothing(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "embedding-reuse@example.com"
        )
        first = make_chunk(repository, repository_index, repository_file, "auth code")
        second = make_chunk(repository, repository_index, repository_file, "auth code")
        session.add(first)
        await session.flush()
        provider = assert_provider_protocol(FakeEmbeddingProvider())

        computed = await embed_repository_chunks([first], provider)
        session.add(second)
        await session.flush()
        reused_computed = await embed_repository_chunks([second], provider)
        rerun_computed = await embed_repository_chunks([first, second], provider)

        assert computed == 1
        assert reused_computed == 0
        assert rerun_computed == 0
        assert provider.call_count == 1
        assert provider.embedded_texts == ["auth code"]
        assert list(first.embedding) == list(second.embedding) == vector(1.0)
        assert first.embedding_model_version == current_embedding_model_version()
        assert second.embedding_model_version == first.embedding_model_version


@pytest.mark.asyncio
async def test_semantic_search_returns_most_similar_scoped_chunk(session_factory) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "semantic-search@example.com"
        )
        auth = make_chunk(repository, repository_index, repository_file, "auth handler")
        database = make_chunk(repository, repository_index, repository_file, "database setup")
        auth.embedding = vector(1.0)
        database.embedding = vector(0.0, 1.0)
        auth.embedding_model_version = current_embedding_model_version()
        database.embedding_model_version = current_embedding_model_version()
        session.add_all([auth, database])
        await session.flush()

        results = await semantic_search(
            repository.id,
            repository_index.id,
            vector(1.0),
            2,
            session=session,
        )

        assert [chunk.content for chunk in results] == ["auth handler", "database setup"]


@pytest.mark.asyncio
async def test_semantic_search_never_crosses_repository_boundary(session_factory) -> None:
    async with session_factory() as session:
        first_repo, first_index, first_file = await make_repository(
            session, "first-repository@example.com"
        )
        second_repo, second_index, second_file = await make_repository(
            session, "second-repository@example.com"
        )
        allowed = make_chunk(first_repo, first_index, first_file, "allowed result")
        excluded = make_chunk(second_repo, second_index, second_file, "closer but excluded")
        allowed.embedding = vector(0.8, 0.2)
        excluded.embedding = vector(1.0)
        allowed.embedding_model_version = current_embedding_model_version()
        excluded.embedding_model_version = current_embedding_model_version()
        session.add_all([allowed, excluded])
        await session.flush()

        results = await semantic_search(
            first_repo.id,
            first_index.id,
            vector(1.0),
            10,
            session=session,
        )

        assert [chunk.id for chunk in results] == [allowed.id]
        assert all(chunk.repository_id == first_repo.id for chunk in results)


@pytest.mark.asyncio
async def test_semantic_search_excludes_stale_embedding_model_vectors(session_factory) -> None:
    async with session_factory() as session:
        repository, index, file = await make_repository(
            session, "stale-vector@example.com"
        )
        current = make_chunk(repository, index, file, "current model")
        stale = make_chunk(repository, index, file, "stale model")
        current.embedding = vector(0.8, 0.2)
        current.embedding_model_version = current_embedding_model_version()
        stale.embedding = vector(1.0)
        stale.embedding_model_version = "older-model:dimensions=384"
        session.add_all([current, stale])
        await session.flush()

        results = await semantic_search(
            repository.id, index.id, vector(1.0), 10, session=session
        )

        assert [item.id for item in results] == [current.id]


@pytest.mark.asyncio
async def test_postgres_pgvector_search_orders_and_limits_scoped_results() -> None:
    database_url = os.getenv("PRISM_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("A dedicated PostgreSQL test URL is not configured")
    if "test" not in (make_url(database_url).database or "").lower():
        pytest.fail("The PostgreSQL integration test requires a test database")

    schema = f"prism_vector_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    engine = None
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            database_url,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    "CREATE INDEX ix_code_chunks_embedding_cosine "
                    "ON code_chunks USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 1)"
                )
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            repository, index, file = await make_repository(
                session, "pgvector@example.com"
            )
            other_repo, other_index, other_file = await make_repository(
                session, "pgvector-other@example.com"
            )
            expected = make_chunk(repository, index, file, "expected")
            farther = make_chunk(repository, index, file, "farther")
            stale = make_chunk(repository, index, file, "stale")
            other = make_chunk(other_repo, other_index, other_file, "other repository")
            expected.embedding = vector(0.9, 0.1)
            farther.embedding = vector(0.0, 1.0)
            stale.embedding = vector(1.0)
            other.embedding = vector(1.0)
            for chunk in (expected, farther, other):
                chunk.embedding_model_version = current_embedding_model_version()
            stale.embedding_model_version = "older-model:dimensions=384"
            session.add_all([expected, farther, stale, other])
            await session.commit()
            await session.execute(text("SET enable_seqscan = off"))

            results = await semantic_search(
                repository.id, index.id, vector(1.0), 1, session=session
            )
            assert [item.id for item in results] == [expected.id]
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
