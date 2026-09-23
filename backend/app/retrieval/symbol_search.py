import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository_index import RepositoryIndex
from app.retrieval.models import RankedChunk

FUZZY_SYMBOL_LIMIT = 10
FUZZY_SIMILARITY_THRESHOLD = 0.3


def _trigrams(value: str) -> Counter[str]:
    padded = f"  {value.lower()} "
    return Counter(padded[index : index + 3] for index in range(len(padded) - 2))


def _trigram_similarity(left: str, right: str) -> float:
    left_trigrams = _trigrams(left)
    right_trigrams = _trigrams(right)
    overlap = sum((left_trigrams & right_trigrams).values())
    total = sum(left_trigrams.values()) + sum(right_trigrams.values())
    return (2.0 * overlap / total) if total else 0.0


async def _candidate_symbols(
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    query_text: str,
    session: AsyncSession,
) -> list[tuple[CodeSymbol, float]]:
    scoped = (
        select(CodeSymbol)
        .join(RepositoryIndex, RepositoryIndex.id == CodeSymbol.repository_index_id)
        .where(
            RepositoryIndex.repository_id == repository_id,
            CodeSymbol.repository_index_id == repository_index_id,
        )
    )
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect != "postgresql":
        symbols = list((await session.scalars(scoped)).all())
        case_sensitive = [symbol for symbol in symbols if symbol.name == query_text]
        case_insensitive = [
            symbol
            for symbol in symbols
            if symbol.name != query_text and symbol.name.lower() == query_text.lower()
        ]
        excluded = {symbol.id for symbol in case_sensitive + case_insensitive}
        fuzzy = sorted(
            (
                (symbol, _trigram_similarity(symbol.name, query_text))
                for symbol in symbols
                if symbol.id not in excluded
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        fuzzy = [
            item for item in fuzzy if item[1] > FUZZY_SIMILARITY_THRESHOLD
        ][:FUZZY_SYMBOL_LIMIT]
        return [
            *((symbol, 1.0) for symbol in case_sensitive),
            *((symbol, 0.95) for symbol in case_insensitive),
            *fuzzy,
        ]

    case_sensitive = list(
        (await session.scalars(scoped.where(CodeSymbol.name == query_text))).all()
    )
    case_insensitive = list(
        (
            await session.scalars(
                scoped.where(
                    func.lower(CodeSymbol.name) == query_text.lower(),
                    CodeSymbol.name != query_text,
                )
            )
        ).all()
    )
    similarity = func.similarity(CodeSymbol.name, query_text)
    fuzzy_statement = (
        select(CodeSymbol, similarity.label("raw_score"))
        .join(RepositoryIndex, RepositoryIndex.id == CodeSymbol.repository_index_id)
        .where(
            RepositoryIndex.repository_id == repository_id,
            CodeSymbol.repository_index_id == repository_index_id,
            func.lower(CodeSymbol.name) != query_text.lower(),
            similarity > FUZZY_SIMILARITY_THRESHOLD,
        )
        .order_by(similarity.desc(), CodeSymbol.name)
        .limit(FUZZY_SYMBOL_LIMIT)
    )
    fuzzy_symbols = list((await session.execute(fuzzy_statement)).all())
    return [
        *((symbol, 1.0) for symbol in case_sensitive),
        *((symbol, 0.95) for symbol in case_insensitive),
        *((symbol, float(score)) for symbol, score in fuzzy_symbols),
    ]


async def symbol_search(
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    query_text: str,
    *,
    session: AsyncSession,
) -> list[RankedChunk]:
    """Map scoped exact and trigram-close symbol matches to owning chunks."""
    query_text = query_text.strip()
    if not query_text:
        return []
    candidates = await _candidate_symbols(
        repository_id, repository_index_id, query_text, session
    )
    if not candidates:
        return []

    file_ids = {symbol.file_id for symbol, _ in candidates}
    chunk_statement = select(CodeChunk).where(
        CodeChunk.repository_id == repository_id,
        CodeChunk.repository_index_id == repository_index_id,
        CodeChunk.file_id.in_(file_ids),
    )
    chunks = list((await session.scalars(chunk_statement)).all())
    best_by_chunk: dict[uuid.UUID, RankedChunk] = {}
    for symbol, score in candidates:
        for chunk in chunks:
            owns_symbol = (
                chunk.file_id == symbol.file_id
                and (
                    chunk.symbol_name == symbol.name
                    or chunk.start_line <= symbol.start_line <= chunk.end_line
                )
            )
            if not owns_symbol:
                continue
            ranked = RankedChunk(chunk=chunk, raw_score=score, signal="symbol")
            previous = best_by_chunk.get(chunk.id)
            if previous is None or ranked.raw_score > previous.raw_score:
                best_by_chunk[chunk.id] = ranked
    return sorted(
        best_by_chunk.values(),
        key=lambda item: (
            -item.raw_score,
            item.chunk.file_path,
            item.chunk.start_line,
        ),
    )
