import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_symbol import CodeSymbol
from app.models.repository_index import RepositoryIndex
from app.retrieval.models import ContainedSymbol, RankedChunk, SymbolMatchType

FUZZY_SYMBOL_LIMIT = 10
# PostgreSQL pg_trgm uses 0.3 as its default similarity threshold. Exact
# matches remain unconditional; fuzzy candidates must be strictly above it.
FUZZY_SIMILARITY_THRESHOLD = 0.3


@dataclass(frozen=True, slots=True)
class _SymbolCandidate:
    symbol: CodeSymbol
    score: float
    match_type: SymbolMatchType


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
) -> list[_SymbolCandidate]:
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
            *(
                _SymbolCandidate(symbol, 1.0, "exact_case_sensitive")
                for symbol in case_sensitive
            ),
            *(
                _SymbolCandidate(symbol, 0.95, "exact_case_insensitive")
                for symbol in case_insensitive
            ),
            *(
                _SymbolCandidate(symbol, score, "fuzzy")
                for symbol, score in fuzzy
            ),
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
        *(
            _SymbolCandidate(symbol, 1.0, "exact_case_sensitive")
            for symbol in case_sensitive
        ),
        *(
            _SymbolCandidate(symbol, 0.95, "exact_case_insensitive")
            for symbol in case_insensitive
        ),
        *(
            _SymbolCandidate(symbol, float(score), "fuzzy")
            for symbol, score in fuzzy_symbols
        ),
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

    file_ids = {candidate.symbol.file_id for candidate in candidates}
    chunk_statement = select(CodeChunk).where(
        CodeChunk.repository_id == repository_id,
        CodeChunk.repository_index_id == repository_index_id,
        CodeChunk.file_id.in_(file_ids),
    )
    chunks = list((await session.scalars(chunk_statement)).all())
    all_symbols = list(
        (
            await session.scalars(
                select(CodeSymbol)
                .where(
                    CodeSymbol.repository_index_id == repository_index_id,
                    CodeSymbol.file_id.in_(file_ids),
                )
                .order_by(
                    CodeSymbol.file_id,
                    CodeSymbol.start_line,
                    CodeSymbol.end_line,
                    CodeSymbol.name,
                )
            )
        ).all()
    )
    best_by_chunk: dict[uuid.UUID, RankedChunk] = {}
    for candidate in candidates:
        symbol = candidate.symbol
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
            contained = ContainedSymbol(
                name=symbol.name,
                file_path=chunk.file_path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                match_type=candidate.match_type,
            )
            previous = best_by_chunk.get(chunk.id)
            contained_symbols = {
                *(previous.contained_symbols if previous is not None else ()),
                contained,
            }
            best_by_chunk[chunk.id] = RankedChunk(
                chunk=chunk,
                raw_score=max(
                    candidate.score,
                    previous.raw_score if previous is not None else float("-inf"),
                ),
                signal="symbol",
                contained_symbols=tuple(
                    sorted(
                        contained_symbols,
                        key=lambda item: (
                            item.file_path,
                            item.start_line,
                            item.end_line,
                            item.name,
                            item.match_type,
                        ),
                    )
                ),
            )
    for chunk_id, ranked in list(best_by_chunk.items()):
        by_location = {
            (item.name, item.start_line, item.end_line): item
            for item in ranked.contained_symbols
        }
        for symbol in all_symbols:
            if symbol.file_id != ranked.chunk.file_id:
                continue
            if not (
                ranked.chunk.start_line <= symbol.start_line <= ranked.chunk.end_line
            ):
                continue
            key = (symbol.name, symbol.start_line, symbol.end_line)
            by_location.setdefault(
                key,
                ContainedSymbol(
                    name=symbol.name,
                    file_path=ranked.chunk.file_path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    match_type="contained",
                ),
            )
        best_by_chunk[chunk_id] = RankedChunk(
            chunk=ranked.chunk,
            raw_score=ranked.raw_score,
            signal=ranked.signal,
            source_chunk_ids=ranked.source_chunk_ids,
            final_score=ranked.final_score,
            raw_signal_scores=dict(ranked.raw_signal_scores),
            contributing_signals=ranked.contributing_signals,
            contained_symbols=tuple(
                sorted(
                    by_location.values(),
                    key=lambda item: (
                        item.file_path,
                        item.start_line,
                        item.end_line,
                        item.name,
                        item.match_type,
                    ),
                )
            ),
        )
    return sorted(
        best_by_chunk.values(),
        key=lambda item: (
            -item.raw_score,
            item.chunk.file_path,
            item.chunk.start_line,
        ),
    )
