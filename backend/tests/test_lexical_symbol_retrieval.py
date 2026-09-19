import hashlib
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    CodeChunk,
    CodeChunkType,
    CodeSymbol,
    Repository,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.retrieval.lexical_search import lexical_search
from app.retrieval.models import RankedChunk
from app.retrieval.symbol_search import symbol_search
import app.retrieval as retrieval


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


async def make_repository(session, email: str):
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
        version=1,
        revision="fixture",
        state=RepositoryIndexState.READY,
    )
    session.add(repository_index)
    await session.flush()
    repository_file = RepositoryFile(
        repository_index_id=repository_index.id,
        path=f"{email}.py",
        language="python",
        content_hash="f" * 64,
        status=RepositoryFileStatus.OK,
        size_bytes=10,
        content="fixture",
    )
    session.add(repository_file)
    await session.flush()
    return repository, repository_index, repository_file


def make_chunk(repository, repository_index, repository_file, content: str, symbol: str):
    chunk = CodeChunk(
        repository_id=repository.id,
        repository_index_id=repository_index.id,
        file_id=repository_file.id,
        file_path=repository_file.path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name=symbol,
        symbol_type="FUNCTION",
        parent_symbol=None,
        start_line=1,
        end_line=5,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        embedding=None,
        chunk_metadata={"source_type": "CODE"},
    )
    symbol_row = CodeSymbol(
        repository_index_id=repository_index.id,
        file_id=repository_file.id,
        name=symbol,
        symbol_type="FUNCTION",
        start_line=1,
        end_line=5,
    )
    return chunk, symbol_row


def test_retrieval_package_exports_semantic_search_and_ranked_chunk() -> None:
    assert "semantic_search" in retrieval.__all__
    assert "RankedChunk" in retrieval.__all__
    assert retrieval.semantic_search is not None
    assert retrieval.RankedChunk is RankedChunk


@pytest.mark.asyncio
async def test_lexical_search_ranks_exact_phrase_above_unrelated_chunk(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "lexical@example.com"
        )
        exact, exact_symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "The login route creates an access token for the authenticated user.",
            "create_access_token",
        )
        unrelated, unrelated_symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "Database migrations create account tables.",
            "run_migrations",
        )
        session.add_all([exact, exact_symbol, unrelated, unrelated_symbol])
        await session.flush()

        results = await lexical_search(
            repository.id,
            repository_index.id,
            "creates an access token",
            session=session,
        )

        assert results
        assert all(isinstance(result, RankedChunk) for result in results)
        assert results[0].chunk.id == exact.id
        assert all(result.signal == "lexical" for result in results)


@pytest.mark.asyncio
async def test_lexical_search_falls_back_to_meaningful_or_terms(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "lexical-natural-language@example.com"
        )
        target, target_symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            '# JWT secret configuration\nJWT_SECRET = os.environ["JWT_SECRET"]',
            "load_jwt_secret",
        )
        session.add_all([target, target_symbol])
        await session.flush()

        results = await lexical_search(
            repository.id,
            repository_index.id,
            "Where is the JWT secret loaded during application startup?",
            session=session,
        )

        assert results
        assert results[0].chunk.id == target.id


@pytest.mark.asyncio
async def test_lexical_search_keeps_strict_path_when_it_has_results(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "lexical-strict@example.com"
        )
        strict, strict_symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "access token authentication",
            "strict_match",
        )
        partial, partial_symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "access access access",
            "partial_match",
        )
        session.add_all([strict, strict_symbol, partial, partial_symbol])
        await session.flush()

        results = await lexical_search(
            repository.id,
            repository_index.id,
            "access token",
            session=session,
        )

        assert [result.chunk.id for result in results] == [strict.id]


@pytest.mark.asyncio
async def test_symbol_search_finds_exact_name(session_factory) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "symbol-exact@example.com"
        )
        chunk, symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "def create_access_token(): pass",
            "create_access_token",
        )
        session.add_all([chunk, symbol])
        await session.flush()

        results = await symbol_search(
            repository.id,
            repository_index.id,
            "create_access_token",
            session=session,
        )

        assert [result.chunk.id for result in results] == [chunk.id]
        assert results[0].raw_score == 1.0
        assert results[0].signal == "symbol"


@pytest.mark.asyncio
async def test_symbol_search_finds_trigram_close_misspelling(session_factory) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "symbol-fuzzy@example.com"
        )
        chunk, symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "def authenticate_user(): pass",
            "authenticate_user",
        )
        session.add_all([chunk, symbol])
        await session.flush()

        results = await symbol_search(
            repository.id,
            repository_index.id,
            "authentcate_user",
            session=session,
        )

        assert results
        assert results[0].chunk.id == chunk.id
        assert 0.0 < results[0].raw_score < 1.0


@pytest.mark.asyncio
async def test_symbol_search_ignores_unrelated_fuzzy_name(session_factory) -> None:
    async with session_factory() as session:
        repository, index, file = await make_repository(
            session, "symbol-unrelated@example.com"
        )
        chunk, symbol = make_chunk(
            repository, index, file, "def authenticate_user(): pass", "authenticate_user"
        )
        session.add_all([chunk, symbol])
        await session.flush()

        results = await symbol_search(
            repository.id, index.id, "quantum_orbit", session=session
        )
        assert results == []


@pytest.mark.asyncio
async def test_symbol_search_short_misspelling_clears_fuzzy_threshold(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "symbol-short-fuzzy@example.com"
        )
        chunk, symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "def hello(): pass",
            "hello",
        )
        session.add_all([chunk, symbol])
        await session.flush()

        results = await symbol_search(
            repository.id,
            repository_index.id,
            "helo",
            session=session,
        )

        assert [result.chunk.id for result in results] == [chunk.id]


@pytest.mark.asyncio
async def test_symbol_search_excludes_unrelated_zero_similarity_matches(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index, repository_file = await make_repository(
            session, "symbol-unrelated@example.com"
        )
        chunk, symbol = make_chunk(
            repository,
            repository_index,
            repository_file,
            "def hello(): pass",
            "hello",
        )
        session.add_all([chunk, symbol])
        await session.flush()

        results = await symbol_search(
            repository.id,
            repository_index.id,
            "database_connection",
            session=session,
        )
        assert results == []


@pytest.mark.asyncio
async def test_postgres_symbol_search_excludes_unrelated_fuzzy_names() -> None:
    database_url = os.getenv("PRISM_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("A dedicated PostgreSQL test URL is not configured")
    if "test" not in (make_url(database_url).database or "").lower():
        pytest.fail("The PostgreSQL integration test requires a test database")

    schema = f"prism_symbol_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    engine = None
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            database_url,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            repository, index, file = await make_repository(
                session, "pg-symbol@example.com"
            )
            chunk, symbol = make_chunk(
                repository, index, file, "def authenticate_user(): pass", "authenticate_user"
            )
            session.add_all([chunk, symbol])
            await session.commit()

            results = await symbol_search(
                repository.id, index.id, "quantum_orbit", session=session
            )
            assert results == []
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_lexical_search_enforces_repository_and_index_isolation(
    session_factory,
) -> None:
    async with session_factory() as session:
        allowed_repo, allowed_index, allowed_file = await make_repository(
            session, "lexical-allowed@example.com"
        )
        other_repo, other_index, other_file = await make_repository(
            session, "lexical-other@example.com"
        )
        allowed, allowed_symbol = make_chunk(
            allowed_repo, allowed_index, allowed_file, "access token", "allowed"
        )
        excluded, excluded_symbol = make_chunk(
            other_repo,
            other_index,
            other_file,
            "access token access token access token",
            "excluded",
        )
        session.add_all([allowed, allowed_symbol, excluded, excluded_symbol])
        await session.flush()

        results = await lexical_search(
            allowed_repo.id,
            allowed_index.id,
            "Where is the access token loaded during startup?",
            session=session,
        )

        assert [result.chunk.id for result in results] == [allowed.id]


@pytest.mark.asyncio
async def test_symbol_search_enforces_repository_and_index_isolation(
    session_factory,
) -> None:
    async with session_factory() as session:
        allowed_repo, allowed_index, allowed_file = await make_repository(
            session, "symbol-allowed@example.com"
        )
        other_repo, other_index, other_file = await make_repository(
            session, "symbol-other@example.com"
        )
        allowed, allowed_symbol = make_chunk(
            allowed_repo,
            allowed_index,
            allowed_file,
            "def target_symbol(): pass",
            "target_symbol",
        )
        excluded, excluded_symbol = make_chunk(
            other_repo,
            other_index,
            other_file,
            "def target_symbol(): pass",
            "target_symbol",
        )
        session.add_all([allowed, allowed_symbol, excluded, excluded_symbol])
        await session.flush()

        results = await symbol_search(
            allowed_repo.id, allowed_index.id, "target_symbol", session=session
        )

        assert [result.chunk.id for result in results] == [allowed.id]
