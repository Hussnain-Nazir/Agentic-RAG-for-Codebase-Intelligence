import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.base import EmbeddingProvider
from app.retrieval.expansion import expand_structurally
from app.retrieval.lexical_search import lexical_search
from app.retrieval.models import RankedChunk
from app.retrieval.ranking import (
    deduplicate_by_chunk_and_overlap,
    merge_adjacent_chunks,
    merge_candidates,
)
from app.retrieval.symbol_search import symbol_search
from app.retrieval.vector_search import semantic_search

SEMANTIC_CANDIDATE_LIMIT = 30
LEXICAL_CANDIDATE_LIMIT = 30


class HybridRetriever:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider

    async def retrieve(
        self,
        repository_id: uuid.UUID,
        repository_index_id: uuid.UUID,
        query_text: str,
    ) -> list[RankedChunk]:
        query_vectors = await self.embedding_provider.embed_batch([query_text])
        if len(query_vectors) != 1:
            raise ValueError("Embedding provider must return one query vector")
        semantic = await semantic_search(
            repository_id,
            repository_index_id,
            query_vectors[0],
            SEMANTIC_CANDIDATE_LIMIT,
            session=self.session,
        )
        lexical = await lexical_search(
            repository_id,
            repository_index_id,
            query_text,
            LEXICAL_CANDIDATE_LIMIT,
            session=self.session,
        )
        symbol = await symbol_search(
            repository_id,
            repository_index_id,
            query_text,
            session=self.session,
        )
        merged = merge_candidates(semantic, lexical, symbol, query_text)
        deduplicated = deduplicate_by_chunk_and_overlap(merged)
        adjacent = merge_adjacent_chunks(deduplicated)
        return await expand_structurally(adjacent, session=self.session)
