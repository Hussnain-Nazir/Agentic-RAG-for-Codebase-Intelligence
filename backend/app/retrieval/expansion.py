import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_relationship import CodeRelationship
from app.models.code_symbol import CodeSymbol
from app.retrieval.models import RankedChunk
from app.retrieval.ranking import sort_ranked

EXPANSION_SEED_LIMIT = 8


def _source_ids(candidate: RankedChunk) -> set[uuid.UUID]:
    return set(candidate.source_chunk_ids or (candidate.chunk.id,))


async def _seed_symbols(
    seed: RankedChunk,
    session: AsyncSession,
) -> list[CodeSymbol]:
    statement = (
        select(CodeSymbol)
        .where(
            CodeSymbol.repository_index_id == seed.chunk.repository_index_id,
            CodeSymbol.file_id == seed.chunk.file_id,
            CodeSymbol.start_line <= seed.chunk.end_line,
            CodeSymbol.end_line >= seed.chunk.start_line,
        )
        .order_by(CodeSymbol.start_line, CodeSymbol.end_line, CodeSymbol.name)
    )
    return list((await session.scalars(statement)).all())


async def _related_symbols(
    seed_symbols: list[CodeSymbol],
    repository_index_id: uuid.UUID,
    session: AsyncSession,
) -> list[CodeSymbol]:
    if not seed_symbols:
        return []
    seed_ids = {symbol.id for symbol in seed_symbols}
    relationships = list(
        (
            await session.scalars(
                select(CodeRelationship)
                .where(
                    CodeRelationship.repository_index_id == repository_index_id,
                    or_(
                        CodeRelationship.from_symbol_id.in_(seed_ids),
                        CodeRelationship.to_symbol_id.in_(seed_ids),
                    ),
                )
                .order_by(
                    CodeRelationship.kind,
                    CodeRelationship.from_symbol_id,
                    CodeRelationship.to_symbol_id,
                    CodeRelationship.id,
                )
            )
        ).all()
    )
    related_ids: set[uuid.UUID] = set()
    for relationship in relationships:
        if relationship.from_symbol_id not in seed_ids:
            related_ids.add(relationship.from_symbol_id)
        if (
            relationship.to_symbol_id is not None
            and relationship.to_symbol_id not in seed_ids
        ):
            related_ids.add(relationship.to_symbol_id)

    parent_names = {
        symbol.parent_symbol for symbol in seed_symbols if symbol.parent_symbol
    }
    conditions = []
    if related_ids:
        conditions.append(CodeSymbol.id.in_(related_ids))
    if parent_names:
        seed_file_ids = {symbol.file_id for symbol in seed_symbols}
        conditions.append(
            CodeSymbol.file_id.in_(seed_file_ids) & CodeSymbol.name.in_(parent_names)
        )
    if not conditions:
        return []
    statement = (
        select(CodeSymbol)
        .where(
            CodeSymbol.repository_index_id == repository_index_id,
            or_(*conditions),
        )
        .order_by(CodeSymbol.file_id, CodeSymbol.start_line, CodeSymbol.name)
    )
    return list((await session.scalars(statement)).all())


async def _chunks_for_symbols(
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    symbols: list[CodeSymbol],
    session: AsyncSession,
) -> list[CodeChunk]:
    if not symbols:
        return []
    file_ids = {symbol.file_id for symbol in symbols}
    chunks = list(
        (
            await session.scalars(
                select(CodeChunk)
                .where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.repository_index_id == repository_index_id,
                    CodeChunk.file_id.in_(file_ids),
                )
                .order_by(CodeChunk.file_path, CodeChunk.start_line, CodeChunk.id)
            )
        ).all()
    )
    matched: dict[uuid.UUID, CodeChunk] = {}
    for symbol in symbols:
        for chunk in chunks:
            if chunk.file_id != symbol.file_id:
                continue
            if (
                chunk.symbol_name == symbol.name
                or chunk.start_line <= symbol.start_line <= chunk.end_line
            ):
                matched[chunk.id] = chunk
    return sorted(
        matched.values(),
        key=lambda chunk: (chunk.file_path, chunk.start_line, str(chunk.id)),
    )


async def expand_structurally(
    top_chunks: list[RankedChunk],
    max_per_seed: int = 2,
    max_total: int = 15,
    *,
    session: AsyncSession,
) -> list[RankedChunk]:
    """Append bounded directly-related chunks for the top eight seeds."""
    if not top_chunks or max_per_seed <= 0 or max_total <= 0:
        return sort_ranked(top_chunks)
    repository_ids = {item.chunk.repository_id for item in top_chunks}
    index_ids = {item.chunk.repository_index_id for item in top_chunks}
    if len(repository_ids) != 1 or len(index_ids) != 1:
        raise ValueError("Structural expansion candidates must share one repository index")
    repository_id = next(iter(repository_ids))
    repository_index_id = next(iter(index_ids))

    existing_ids = {
        source_id for candidate in top_chunks for source_id in _source_ids(candidate)
    }
    additions: list[RankedChunk] = []
    for seed in sort_ranked(top_chunks)[:EXPANSION_SEED_LIMIT]:
        if len(additions) >= max_total:
            break
        seed_symbols = await _seed_symbols(seed, session)
        related_symbols = await _related_symbols(
            seed_symbols, repository_index_id, session
        )
        related_chunks = await _chunks_for_symbols(
            repository_id, repository_index_id, related_symbols, session
        )
        added_for_seed = 0
        for chunk in related_chunks:
            if chunk.id in existing_ids:
                continue
            additions.append(
                RankedChunk(
                    chunk=chunk,
                    raw_score=seed.raw_score,
                    signal="structural",
                    source_chunk_ids=(chunk.id,),
                    final_score=seed.raw_score,
                    raw_signal_scores={},
                    contributing_signals=("structural",),
                    contained_symbols=(),
                    relationship_metadata={
                        "related_to_chunk_id": str(seed.chunk.id),
                        "kind": "structural_neighbor",
                    },
                )
            )
            existing_ids.add(chunk.id)
            added_for_seed += 1
            if added_for_seed >= max_per_seed or len(additions) >= max_total:
                break
    return sort_ranked([*top_chunks, *additions])
