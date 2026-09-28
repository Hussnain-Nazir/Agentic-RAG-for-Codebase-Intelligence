from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.tools.errors import WebSearchProviderError

SERPAPI_SEARCH_URL = "https://serpapi.com/search"


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str
    source_domain: str


class WebSearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[WebResult]: ...


class SerpApiProvider:
    """SerpAPI Google Search provider using the documented /search contract."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 8.0,
    ) -> None:
        configured = settings or get_settings()
        self._api_key = configured.serpapi_api_key
        self._client = client
        self._timeout_s = timeout_s

    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        if not self._api_key:
            raise WebSearchProviderError("SerpAPI is not configured")
        params = {
            "engine": "google",
            "q": query,
            "api_key": self._api_key,
            "output": "json",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout_s)
        try:
            response = await client.get(SERPAPI_SEARCH_URL, params=params)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("error"):
                raise WebSearchProviderError("SerpAPI search failed")
            results: list[WebResult] = []
            for item in payload.get("organic_results", []):
                url = item.get("link")
                if not isinstance(url, str) or not url:
                    continue
                results.append(
                    WebResult(
                        title=str(item.get("title") or "Untitled result"),
                        url=url,
                        snippet=str(item.get("snippet") or ""),
                        source_domain=urlparse(url).netloc.lower(),
                    )
                )
                if len(results) >= max_results:
                    break
            return results
        except WebSearchProviderError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise WebSearchProviderError("SerpAPI request failed") from exc
        finally:
            if owns_client:
                await client.aclose()
