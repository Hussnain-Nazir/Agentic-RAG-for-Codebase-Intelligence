import hashlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    CodeChunk,
    CodeChunkType,
    CodeRelationship,
    CodeRelationshipConfidence,
    CodeRelationshipKind,
    CodeSymbol,
    Repository,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.retrieval.expansion import expand_structurally
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import ContainedSymbol, RankedChunk
from app.retrieval.ranking import (
    deduplicate_by_chunk_and_overlap,
    merge_adjacent_chunks,
    merge_candidates,
)


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 382)]


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [vector(1.0) for _ in texts]


def transient_chunk(
    *,
    file_path: str,
    start_line: int,
    end_line: int,
    symbol_name: str,
    content: str | None = None,
) -> CodeChunk:
    value = content or f"def {symbol_name}(): pass"
    return CodeChunk(
        id=uuid.uuid4(),
        repository_id=uuid.UUID(int=1),
        repository_index_id=uuid.UUID(int=2),
        file_id=uuid.uuid5(uuid.NAMESPACE_URL, file_path),
        file_path=file_path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name=symbol_name,
        symbol_type="FUNCTION",
        parent_symbol=None,
        start_line=start_line,
        end_line=end_line,
        content=value,
        content_hash=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        embedding=None,
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


async def make_repository(session):
    user = User(email=f"hybrid-{uuid.uuid4()}@example.com", hashed_password="unused")
    session.add(user)
    await session.flush()
    repository = Repository(
        owner_id=user.id,
        source_type=RepositorySourceType.UPLOAD,
        name="hybrid-fixture",
        default_branch="upload",
        selected_branch="upload",
    )
    session.add(repository)
    await session.flush()
    repository_index = RepositoryIndex(
        repository_id=repository.id,
        version=1,
        revision="hybrid-fixture",
        state=RepositoryIndexState.READY,
    )
    session.add(repository_index)
    await session.flush()
    return repository, repository_index


async def add_symbol_chunk(
    session,
    repository,
    repository_index,
    *,
    path: str,
    symbol_name: str,
    content: str,
    embedding: list[float] | None = None,
):
    repository_file = RepositoryFile(
        repository_index_id=repository_index.id,
        path=path,
        language="python",
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        status=RepositoryFileStatus.OK,
        size_bytes=len(content),
        content=content,
    )
    session.add(repository_file)
    await session.flush()
    symbol = CodeSymbol(
        repository_index_id=repository_index.id,
        file_id=repository_file.id,
        name=symbol_name,
        symbol_type="FUNCTION",
        start_line=1,
        end_line=3,
    )
    chunk = CodeChunk(
        repository_id=repository.id,
        repository_index_id=repository_index.id,
        file_id=repository_file.id,
        file_path=path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name=symbol_name,
        symbol_type="FUNCTION",
        parent_symbol=None,
        start_line=1,
        end_line=3,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        embedding=embedding,
        chunk_metadata={"source_type": "CODE"},
    )
    session.add_all([symbol, chunk])
    await session.flush()
    return symbol, chunk


def test_exact_symbol_boost_outranks_stronger_semantic_candidate() -> None:
    exact = transient_chunk(
        file_path="auth.py",
        start_line=1,
        end_line=4,
        symbol_name="authenticate_user",
    )
    semantic_only = transient_chunk(
        file_path="service.py",
        start_line=10,
        end_line=15,
        symbol_name="verify_credentials",
    )

    merged = merge_candidates(
        semantic=[
            RankedChunk(exact, 0.8, "semantic"),
            RankedChunk(semantic_only, 0.99, "semantic"),
        ],
        lexical=[],
        symbol=[RankedChunk(exact, 1.0, "symbol")],
        query_text="Explain authenticate_user",
    )

    assert merged[0].chunk.id == exact.id
    assert merged[0].raw_score > merged[1].raw_score


def test_contained_exact_symbol_boosts_chunk_without_symbol_name() -> None:
    chunk = transient_chunk(
        file_path="auth/security.py",
        start_line=4,
        end_line=18,
        symbol_name="placeholder",
    )
    chunk.symbol_name = None
    symbol_match = RankedChunk(
        chunk,
        1.0,
        "symbol",
        contained_symbols=(
            ContainedSymbol(
                name="create_access_token",
                file_path=chunk.file_path,
                start_line=6,
                end_line=8,
                match_type="exact_case_sensitive",
            ),
        ),
    )

    merged = merge_candidates([], [], [symbol_match], "create_access_token")

    assert len(merged) == 1
    assert merged[0].raw_score == pytest.approx(0.7)
    assert merged[0].contained_symbols == symbol_match.contained_symbols


def test_adjacent_evidence_unit_receives_exact_boost_once() -> None:
    exact = transient_chunk(
        file_path="auth/security.py",
        start_line=4,
        end_line=8,
        symbol_name="placeholder",
    )
    exact.symbol_name = None
    adjacent = transient_chunk(
        file_path="auth/security.py",
        start_line=10,
        end_line=13,
        symbol_name="verify_password",
    )
    exact_ranked = merge_candidates(
        [],
        [],
        [
            RankedChunk(
                exact,
                1.0,
                "symbol",
                contained_symbols=(
                    ContainedSymbol(
                        name="create_access_token",
                        file_path=exact.file_path,
                        start_line=5,
                        end_line=7,
                        match_type="exact_case_sensitive",
                    ),
                ),
            )
        ],
        "create_access_token",
    )[0]

    merged = merge_adjacent_chunks(
        [exact_ranked, RankedChunk(adjacent, 0.6, "hybrid")]
    )

    assert len(merged) == 1
    assert merged[0].raw_score == pytest.approx(0.7)
    assert [item.name for item in merged[0].contained_symbols] == [
        "create_access_token"
    ]


def test_case_insensitive_exact_boosts_but_fuzzy_only_does_not() -> None:
    exact = transient_chunk(
        file_path="exact.py",
        start_line=1,
        end_line=3,
        symbol_name="placeholder",
    )
    exact.symbol_name = None
    fuzzy = transient_chunk(
        file_path="fuzzy.py",
        start_line=1,
        end_line=3,
        symbol_name="placeholder",
    )
    fuzzy.symbol_name = None

    exact_result = merge_candidates(
        [],
        [],
        [
            RankedChunk(
                exact,
                0.95,
                "symbol",
                contained_symbols=(
                    ContainedSymbol(
                        "CreateAccessToken",
                        exact.file_path,
                        1,
                        3,
                        "exact_case_insensitive",
                    ),
                ),
            )
        ],
        "createaccesstoken",
    )[0]
    fuzzy_result = merge_candidates(
        [],
        [],
        [
            RankedChunk(
                fuzzy,
                0.8,
                "symbol",
                contained_symbols=(
                    ContainedSymbol(
                        "create_access_token",
                        fuzzy.file_path,
                        1,
                        3,
                        "fuzzy",
                    ),
                ),
            )
        ],
        "create_access_tken",
    )[0]

    assert exact_result.raw_score == pytest.approx(0.7)
    assert fuzzy_result.raw_score == pytest.approx(0.2)


def test_merge_uses_frozen_signal_weights() -> None:
    semantic_winner = transient_chunk(
        file_path="semantic.py",
        start_line=1,
        end_line=3,
        symbol_name="semantic_winner",
    )
    lexical_winner = transient_chunk(
        file_path="lexical.py",
        start_line=1,
        end_line=3,
        symbol_name="lexical_winner",
    )
    symbol_only = transient_chunk(
        file_path="symbol.py",
        start_line=1,
        end_line=3,
        symbol_name="symbol_only",
    )

    merged = merge_candidates(
        semantic=[
            RankedChunk(semantic_winner, 2.0, "semantic"),
            RankedChunk(lexical_winner, 1.0, "semantic"),
        ],
        lexical=[
            RankedChunk(lexical_winner, 2.0, "lexical"),
            RankedChunk(semantic_winner, 1.0, "lexical"),
        ],
        symbol=[RankedChunk(symbol_only, 0.8, "symbol")],
        query_text="unrelated query",
    )

    scores = {item.chunk.id: item.raw_score for item in merged}
    assert scores[semantic_winner.id] == pytest.approx(0.5)
    assert scores[lexical_winner.id] == pytest.approx(0.3)
    assert scores[symbol_only.id] == pytest.approx(0.2)
    assert [item.chunk.id for item in merged] == [
        semantic_winner.id,
        lexical_winner.id,
        symbol_only.id,
    ]
    by_id = {item.chunk.id: item for item in merged}
    assert by_id[semantic_winner.id].final_score == pytest.approx(0.5)
    assert by_id[semantic_winner.id].raw_signal_scores == {
        "semantic": 2.0,
        "lexical": 1.0,
    }
    assert by_id[semantic_winner.id].contributing_signals == (
        "semantic",
        "lexical",
    )


def test_duplicate_chunk_id_collapses_to_max_score() -> None:
    chunk = transient_chunk(
        file_path="auth.py",
        start_line=1,
        end_line=5,
        symbol_name="authenticate_user",
    )

    result = deduplicate_by_chunk_and_overlap(
        [
            RankedChunk(chunk, 0.4, "hybrid"),
            RankedChunk(chunk, 0.9, "hybrid"),
        ]
    )

    assert len(result) == 1
    assert result[0].raw_score == 0.9


def test_overlapping_candidates_collapse_to_higher_score() -> None:
    stronger = transient_chunk(
        file_path="auth.py",
        start_line=1,
        end_line=10,
        symbol_name="authenticate_user",
    )
    weaker = transient_chunk(
        file_path="auth.py",
        start_line=5,
        end_line=12,
        symbol_name="verify_password",
    )

    result = deduplicate_by_chunk_and_overlap(
        [
            RankedChunk(weaker, 0.7, "hybrid"),
            RankedChunk(stronger, 0.9, "hybrid"),
        ]
    )

    assert [item.chunk.id for item in result] == [stronger.id]


def test_adjacent_candidates_merge_into_one_evidence_unit() -> None:
    first = transient_chunk(
        file_path="auth.py",
        start_line=1,
        end_line=5,
        symbol_name="authenticate_user",
        content="first",
    )
    second = transient_chunk(
        file_path="auth.py",
        start_line=9,
        end_line=12,
        symbol_name="create_access_token",
        content="second",
    )

    result = merge_adjacent_chunks(
        [
            RankedChunk(first, 0.9, "hybrid"),
            RankedChunk(second, 0.8, "hybrid"),
        ]
    )

    assert len(result) == 1
    assert result[0].chunk.start_line == 1
    assert result[0].chunk.end_line == 12
    assert result[0].source_chunk_ids == tuple(sorted((first.id, second.id), key=str))
    assert result[0].chunk.chunk_metadata["merged_adjacent"] is True


@pytest.mark.asyncio
async def test_structural_expansion_pulls_relationship_and_caps_additions(
    session_factory,
) -> None:
    async with session_factory() as session:
        repository, repository_index = await make_repository(session)
        seed_symbol, seed_chunk = await add_symbol_chunk(
            session,
            repository,
            repository_index,
            path="seed.py",
            symbol_name="seed",
            content="def seed(): pass",
        )
        related_chunks: list[CodeChunk] = []
        for number in range(16):
            symbol, chunk = await add_symbol_chunk(
                session,
                repository,
                repository_index,
                path=f"related_{number:02}.py",
                symbol_name=f"related_{number:02}",
                content=f"def related_{number:02}(): pass",
            )
            related_chunks.append(chunk)
            session.add(
                CodeRelationship(
                    repository_index_id=repository_index.id,
                    from_symbol_id=seed_symbol.id,
                    to_symbol_id=symbol.id,
                    kind=CodeRelationshipKind.CALLS,
                    confidence=CodeRelationshipConfidence.HIGH,
                )
            )
        await session.flush()
        seed = RankedChunk(seed_chunk, 1.0, "hybrid")

        default_result = await expand_structurally([seed], session=session)
        capped_result = await expand_structurally(
            [seed], max_per_seed=20, max_total=15, session=session
        )

        assert len(default_result) == 3
        assert default_result[1].chunk.id in {item.id for item in related_chunks}
        assert sum(item.signal == "structural" for item in capped_result) == 15
        assert len(capped_result) == 16


@pytest.mark.asyncio
async def test_hybrid_retriever_is_deterministic(session_factory) -> None:
    async with session_factory() as session:
        repository, repository_index = await make_repository(session)
        await add_symbol_chunk(
            session,
            repository,
            repository_index,
            path="auth.py",
            symbol_name="authenticate_user",
            content="def authenticate_user(): return access_token",
            embedding=vector(0.9, 0.1),
        )
        await add_symbol_chunk(
            session,
            repository,
            repository_index,
            path="tokens.py",
            symbol_name="create_access_token",
            content="def create_access_token(): return token",
            embedding=vector(0.8, 0.2),
        )
        await add_symbol_chunk(
            session,
            repository,
            repository_index,
            path="database.py",
            symbol_name="open_database",
            content="def open_database(): return connection",
            embedding=vector(0.0, 1.0),
        )
        retriever = HybridRetriever(
            session=session,
            embedding_provider=FakeEmbeddingProvider(),
        )

        first = await retriever.retrieve(
            repository.id, repository_index.id, "authenticate_user"
        )
        second = await retriever.retrieve(
            repository.id, repository_index.id, "authenticate_user"
        )

        assert first
        assert [item.chunk.id for item in first] == [item.chunk.id for item in second]
        assert [item.raw_score for item in first] == [item.raw_score for item in second]
        assert all(item.final_score == item.raw_score for item in first)
        assert all(item.contributing_signals for item in first)
        assert all(
            item.raw_signal_scores or item.signal == "structural" for item in first
        )
