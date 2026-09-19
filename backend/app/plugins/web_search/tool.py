import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_source import WebSource
from app.plugins.web_search.provider import WebResult, WebSearchProvider
from app.tools.base import ExecutionContext

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


def _query_hash(query: str, max_results: int) -> str:
    value = f"{_normalized_query(query)}\nlimit={max_results}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        del ctx
        request = SearchWebInput.model_validate(input)
        return await self.search(request.query, request.max_results)

    async def search(self, query: str, max_results: int = 5) -> SearchWebOutput:
        # Phase 17 must call is_external_doc_query before invoking this tool.
        # Once explicitly invoked, this tool always executes or returns a cache hit.
        normalized = _normalized_query(query)
        query_hash = _query_hash(normalized, max_results)
        cutoff = datetime.now(UTC) - WEB_CACHE_TTL
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

        await self._session.execute(
            delete(WebSource).where(WebSource.query_hash == query_hash)
        )
        try:
            results = await asyncio.wait_for(
                self._provider.search(normalized, max_results),
                timeout=WEB_SEARCH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            error = "Web search timed out" if isinstance(exc, TimeoutError) else "Web search failed"
            return SearchWebOutput(results=[], error=error)

        retrieved_at = datetime.now(UTC)
        for position, result in enumerate(results):
            self._session.add(
                WebSource(
                    query_hash=query_hash,
                    position=position,
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                    source_domain=result.source_domain,
                    retrieved_at=retrieved_at,
                )
            )
        await self._session.flush()
        return SearchWebOutput(results=results, cached=False)
