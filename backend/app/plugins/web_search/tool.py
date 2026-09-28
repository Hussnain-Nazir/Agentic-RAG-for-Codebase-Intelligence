import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_source import WebSource
from app.plugins.web_search.provider import WebResult, WebSearchProvider
from app.tools.base import ExecutionContext
from app.tools.errors import UnauthorizedRepositoryAccessError
from app.tools.repository_context import authorize_repository

WEB_SEARCH_TIMEOUT_SECONDS = 8
WEB_CACHE_TTL = timedelta(hours=24)
EXTERNAL_DOC_TRIGGER_PHRASES = (
    "deprecated",
    "official docs",
    "current version",
    "compare with documentation",
    "latest api",
)


class SearchWebInput(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=5)


class SearchWebOutput(BaseModel):
    results: list[WebResult]
    error: str | None = None
    cached: bool = False


def is_external_doc_query(query: str) -> bool:
    """Classification helper for the Phase 17 caller, not an execution gate."""
    normalized = " ".join(query.lower().split())
    return any(phrase in normalized for phrase in EXTERNAL_DOC_TRIGGER_PHRASES)


def _normalized_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip()).lower()


def _query_hash(query: str) -> str:
    return hashlib.sha256(_normalized_query(query).encode("utf-8")).hexdigest()


class SearchWebTool:
    name = "search_web"
    description = "Search current external documentation through SerpAPI."
    input_schema = SearchWebInput
    output_schema = SearchWebOutput
    requires_auth = True

    def __init__(
        self,
        session: AsyncSession,
        provider: WebSearchProvider,
    ) -> None:
        self._session = session
        self._provider = provider

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        if ctx.repository_id is None:
            raise UnauthorizedRepositoryAccessError("Repository context is required")
        await authorize_repository(self._session, ctx.repository_id, ctx)
        request = SearchWebInput.model_validate(input)
        return await self.search(request.query, request.max_results)

    async def search(self, query: str, max_results: int = 5) -> SearchWebOutput:
        # Phase 17 must call is_external_doc_query before invoking this tool.
        # Once explicitly invoked, this tool always executes or returns a cache hit.
        normalized = _normalized_query(query)
        query_hash = _query_hash(normalized)
        cutoff = datetime.now(UTC) - WEB_CACHE_TTL
        expired = await self._session.scalar(
            select(WebSource.id).where(WebSource.retrieved_at < cutoff).limit(1)
        )
        if expired is not None:
            await self._session.execute(
                delete(WebSource).where(WebSource.retrieved_at < cutoff)
            )
        cached_rows = list(
            await self._session.scalars(
                select(WebSource)
                .where(
                    WebSource.query_hash == query_hash,
                    WebSource.retrieved_at >= cutoff,
                )
                .order_by(WebSource.position, WebSource.id)
            )
        )
        if cached_rows:
            return SearchWebOutput(
                results=[
                    WebResult(
                        title=row.title,
                        url=row.url,
                        snippet=row.snippet,
                        source_domain=row.source_domain,
                    )
                    for row in cached_rows[:max_results]
                ],
                cached=True,
            )

        try:
            results = await asyncio.wait_for(
                self._provider.search(normalized, 5),
                timeout=WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            error = "Web search timed out" if isinstance(exc, TimeoutError) else "Web search failed"
            return SearchWebOutput(results=[], error=error)

        results = results[:5]
        retrieved_at = datetime.now(UTC)
        dialect = self._session.bind.dialect.name if self._session.bind is not None else ""
        for position, result in enumerate(results):
            values = {
                "query_hash": query_hash,
                "position": position,
                "url": result.url,
                "title": result.title,
                "snippet": result.snippet,
                "source_domain": result.source_domain,
                "retrieved_at": retrieved_at,
            }
            if dialect in {"postgresql", "sqlite"}:
                statement = (
                    postgres_insert(WebSource)
                    if dialect == "postgresql"
                    else sqlite_insert(WebSource)
                ).values(**values)
                await self._session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[WebSource.query_hash, WebSource.url],
                        set_={
                            "position": position,
                            "title": result.title,
                            "snippet": result.snippet,
                            "source_domain": result.source_domain,
                            "retrieved_at": retrieved_at,
                        },
                    )
                )
            else:
                self._session.add(WebSource(**values))
        await self._session.flush()
        return SearchWebOutput(results=results[:max_results], cached=False)
