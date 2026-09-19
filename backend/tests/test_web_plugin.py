import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.models import WebSource
from app.plugins.web_search.provider import SerpApiProvider, WebResult
from app.plugins.web_search.tool import (
    SearchWebInput,
    SearchWebTool,
    WEB_CACHE_TTL,
    _query_hash,
)
from app.tools.base import ExecutionContext
from app.tools.registry import ToolRegistry


@pytest_asyncio.fixture
async def web_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_serpapi_success_maps_documented_organic_results(web_session) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/search"
        assert request.url.params["engine"] == "google"
        assert request.url.params["q"] == "python official docs"
        assert request.url.params["api_key"] == "test-only-key"
        assert request.url.params["output"] == "json"
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Python documentation",
                        "link": "https://docs.python.org/3/",
                        "snippet": "Official Python documentation.",
                    }
                ]
            },
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SerpApiProvider(
        settings=Settings(serpapi_api_key="test-only-key"),
        client=client,
    )
    output = await SearchWebTool(web_session, provider).execute(
        SearchWebInput(query="Python official docs"), ExecutionContext()
    )

    assert len(requests) == 1
    assert output.error is None
    assert output.cached is False
    assert output.results == [
        WebResult(
            title="Python documentation",
            url="https://docs.python.org/3/",
            snippet="Official Python documentation.",
            source_domain="docs.python.org",
        )
    ]
    cached_row = await web_session.scalar(select(WebSource))
    assert cached_row is not None
    assert "test-only-key" not in repr(cached_row.__dict__)
    await client.aclose()


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        self.calls += 1
        return [
            WebResult(
                title="FastAPI documentation",
                url="https://fastapi.tiangolo.com/",
                snippet=f"Results for {query}",
                source_domain="fastapi.tiangolo.com",
            )
        ][:max_results]


@pytest.mark.asyncio
async def test_cached_query_within_ttl_skips_provider(web_session) -> None:
    provider = CountingProvider()
    tool = SearchWebTool(web_session, provider)

    first = await tool.search("current version FastAPI")
    second = await tool.search("  CURRENT   VERSION fastapi  ")

    assert provider.calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.results == first.results


@pytest.mark.asyncio
async def test_cache_reuses_full_result_set_for_different_limits(web_session) -> None:
    class FiveResultProvider:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
            del query
            self.calls.append(max_results)
            return [
                WebResult(
                    title=f"Result {number}",
                    url=f"https://docs.example.test/{number}",
                    snippet="Documentation",
                    source_domain="docs.example.test",
                )
                for number in range(5)
            ]

    provider = FiveResultProvider()
    tool = SearchWebTool(web_session, provider)
    first = await tool.search("Current Version FastAPI", 1)
    second = await tool.search(" current   version fastapi ", 5)

    assert len(first.results) == 1
    assert len(second.results) == 5
    assert second.cached is True
    assert provider.calls == [5]


@pytest.mark.asyncio
async def test_expired_rows_for_other_queries_are_pruned(web_session) -> None:
    old = WebSource(
        query_hash="a" * 64,
        position=0,
        url="https://old.example.test/",
        title="Old",
        snippet="Expired",
        source_domain="old.example.test",
        retrieved_at=datetime.now(UTC) - WEB_CACHE_TTL - timedelta(minutes=1),
    )
    web_session.add(old)
    await web_session.flush()

    await SearchWebTool(web_session, CountingProvider()).search("official docs")

    assert await web_session.get(WebSource, old.id) is None


@pytest.mark.asyncio
async def test_cache_upsert_handles_row_inserted_after_cache_miss(web_session) -> None:
    result = WebResult(
        title="Documentation",
        url="https://docs.example.test/current",
        snippet="Current API",
        source_domain="docs.example.test",
    )

    class RacingProvider:
        async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
            del max_results
            web_session.add(
                WebSource(
                    query_hash=_query_hash(query),
                    position=0,
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                    source_domain=result.source_domain,
                    retrieved_at=datetime.now(UTC),
                )
            )
            await web_session.flush()
            return [result]

    output = await SearchWebTool(web_session, RacingProvider()).search("official docs")
    rows = list(await web_session.scalars(select(WebSource)))

    assert output.results == [result]
    assert len(rows) == 1


class FailingProvider:
    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        del query, max_results
        raise RuntimeError("failure containing secret-key-value")


@pytest.mark.asyncio
async def test_provider_error_returns_empty_results_without_secret(web_session) -> None:
    output = await SearchWebTool(web_session, FailingProvider()).search("latest api")

    assert output.results == []
    assert output.error == "Web search failed"
    assert "secret-key-value" not in output.error


class SlowProvider:
    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        del query, max_results
        await asyncio.sleep(0.1)
        return []


@pytest.mark.asyncio
async def test_timeout_returns_empty_results(monkeypatch, web_session) -> None:
    monkeypatch.setattr(
        "app.plugins.web_search.tool.WEB_SEARCH_TIMEOUT_SECONDS", 0.01
    )

    output = await SearchWebTool(web_session, SlowProvider()).search("official docs")

    assert output.results == []
    assert output.error == "Web search timed out"


@pytest.mark.asyncio
async def test_registry_registers_file_and_web_plugin_tools(web_session) -> None:
    registry = ToolRegistry()
    registry.register_builtin_plugins(
        session=web_session,
        web_search_provider=CountingProvider(),
    )

    assert [tool.name for tool in registry.list()] == [
        "search_codebase",
        "find_symbol",
        "find_references",
        "read_file",
        "read_file_range",
        "get_related_files",
        "inspect_repository",
        "retrieve_memory",
        "save_memory",
        "get_review_history",
        "search_web",
    ]
