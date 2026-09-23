import math
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ingestion.embedding_stage import current_embedding_model_version
from app.models.code_chunk import CodeChunk

EMBEDDING_DIMENSIONS = 384


def _as_floats(vector: object) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]  # type: ignore[union-attr]


def _cosine_distance(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 1.0
    similarity = sum(a * b for a, b in zip(left, right, strict=True))
    return 1.0 - similarity / (left_norm * right_norm)


async def semantic_search(
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int,
    *,
    session: AsyncSession,
    settings: Settings | None = None,
) -> list[CodeChunk]:
    """Return scoped chunks ordered by cosine distance."""
    if top_k <= 0:
        return []
    if len(query_embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Query embedding must have {EMBEDDING_DIMENSIONS} dimensions"
        )
    active_version = current_embedding_model_version(settings)

    scoped = (
        select(CodeChunk)
        .where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.repository_index_id == repository_index_id,
            CodeChunk.embedding.is_not(None),
            CodeChunk.embedding_model_version == active_version,
        )
    )
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect == "postgresql":
        statement = (
            scoped.order_by(CodeChunk.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        return list((await session.scalars(statement)).all())

    candidates = list((await session.scalars(scoped)).all())
    candidates.sort(
        key=lambda chunk: _cosine_distance(
            _as_floats(chunk.embedding), query_embedding
        )
    )
    return candidates[:top_k]
