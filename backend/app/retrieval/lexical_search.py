import re
import uuid
from collections import Counter

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.retrieval.models import RankedChunk

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _tokens(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(value)]


def _fallback_score(content: str, query_text: str) -> float:
    query_tokens = _tokens(query_text)
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    counts = Counter(content_tokens)
    matched = sum(counts[token] for token in query_tokens)
    phrase_bonus = 1.0 if query_text.lower() in content.lower() else 0.0
    coverage = sum(token in counts for token in set(query_tokens)) / len(set(query_tokens))
    return float(matched) + phrase_bonus + coverage


async def lexical_search(
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    query_text: str,
    top_k: int = 30,
    *,
    session: AsyncSession,
) -> list[RankedChunk]:
    """Return repository-scoped chunks ranked by lexical relevance."""
    query_text = query_text.strip()
    if top_k <= 0 or not query_text:
        return []

    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect == "postgresql":
        search_vector = literal_column("code_chunks.search_vector")
        english = literal_column("'english'::regconfig")
        query = func.plainto_tsquery(english, query_text)
        rank = func.ts_rank_cd(search_vector, query).label("raw_score")
        statement = (
            select(CodeChunk, rank)
            .where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.repository_index_id == repository_index_id,
                search_vector.op("@@")(query),
            )
            .order_by(rank.desc(), CodeChunk.id)
            .limit(top_k)
        )
        rows = (await session.execute(statement)).all()
        return [
            RankedChunk(chunk=chunk, raw_score=float(score), signal="lexical")
            for chunk, score in rows
        ]

    scoped = select(CodeChunk).where(
        CodeChunk.repository_id == repository_id,
        CodeChunk.repository_index_id == repository_index_id,
    )
    chunks = list((await session.scalars(scoped)).all())
    scored = [
        (chunk, _fallback_score(chunk.content, query_text)) for chunk in chunks
    ]
    scored = [item for item in scored if item[1] > 0]
    scored.sort(key=lambda item: (-item[1], item[0].file_path, item[0].start_line))
    return [
        RankedChunk(chunk=chunk, raw_score=score, signal="lexical")
        for chunk, score in scored[:top_k]
    ]
