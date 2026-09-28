from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_object_session

from app.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.models.code_chunk import CodeChunk

EMBEDDING_DIMENSIONS = 384


def current_embedding_model_version(settings: Settings | None = None) -> str:
    configured = settings or get_settings()
    return f"{configured.embedding_model_name}:dimensions={EMBEDDING_DIMENSIONS}"


def _vector_values(vector: object) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]  # type: ignore[union-attr]


async def embed_repository_chunks(
    chunks: list[CodeChunk],
    provider: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    embedding_model_version: str | None = None,
) -> int:
    """Embed missing or stale chunks and return the number of computed texts."""
    if not chunks:
        return 0
    if provider.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding provider must produce {EMBEDDING_DIMENSIONS} dimensions"
        )
    session = async_object_session(chunks[0])
    if session is None:
        raise ValueError("Code chunks must be attached to an AsyncSession")

    version = embedding_model_version or current_embedding_model_version(settings)
    pending = [
        chunk
        for chunk in chunks
        if chunk.embedding is None or chunk.embedding_model_version != version
    ]
    if not pending:
        return 0

    by_hash: dict[str, list[CodeChunk]] = defaultdict(list)
    for chunk in pending:
        by_hash[chunk.content_hash].append(chunk)

    cached_rows = await session.execute(
        select(CodeChunk.content_hash, CodeChunk.embedding).where(
            CodeChunk.content_hash.in_(list(by_hash)),
            CodeChunk.embedding_model_version == version,
            CodeChunk.embedding.is_not(None),
        )
    )
    cached: dict[str, list[float]] = {}
    for content_hash, embedding in cached_rows:
        cached.setdefault(content_hash, _vector_values(embedding))

    for content_hash in list(by_hash):
        if content_hash not in cached:
            continue
        for chunk in by_hash.pop(content_hash):
            chunk.embedding = cached[content_hash]
            chunk.embedding_model_version = version

    representatives = [group[0] for group in by_hash.values()]
    if representatives:
        vectors = await provider.embed_batch([chunk.content for chunk in representatives])
        if len(vectors) != len(representatives):
            raise ValueError("Embedding provider returned an unexpected vector count")
        for representative, vector in zip(representatives, vectors, strict=True):
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(
                    f"Embedding provider returned {len(vector)} dimensions, "
                    f"expected {EMBEDDING_DIMENSIONS}"
                )
            values = [float(value) for value in vector]
            for chunk in by_hash[representative.content_hash]:
                chunk.embedding = values
                chunk.embedding_model_version = version

    await session.flush()
    return len(representatives)
