import asyncio
import base64
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import jwt

from app.config import Settings, get_settings
from app.github.errors import (
    GitHubAccessLost,
    GitHubApiError,
    GitHubBranchMissing,
    GitHubInstallationRevoked,
    GitHubRateLimited,
    GitHubRepositoryDeleted,
)

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CachedInstallationToken:
    value: str
    expires_at: datetime


class GitHubClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str = "https://api.github.com",
        oauth_base_url: str = "https://github.com",
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = base_url.rstrip("/")
        self._oauth_base_url = oauth_base_url.rstrip("/")
        self._transport = transport
        self._sleep = sleep
        self._token_cache: dict[int, CachedInstallationToken] = {}
        self._http_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(transport=self._transport, timeout=20)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None

    @property
    def user_authorization_configured(self) -> bool:
        return bool(
            self._settings.github_client_id
            and self._settings.github_client_secret
        )

    def _app_jwt(self) -> str:
        if not self._settings.github_app_id:
            raise GitHubApiError("GITHUB_APP_ID is not configured")
        key_path = Path(self._settings.github_app_private_key_path)
        try:
            private_key = key_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GitHubApiError("GitHub App private key could not be read") from exc
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iat": int((now - timedelta(seconds=60)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": self._settings.github_app_id,
            },
            private_key,
            algorithm="RS256",
        )

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        token: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        error_kind: str = "api",
    ) -> httpx.Response:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            requested = urlsplit(path_or_url)
            configured = urlsplit(self._base_url)
            if (requested.scheme, requested.netloc) != (
                configured.scheme,
                configured.netloc,
            ):
                raise GitHubApiError("GitHub pagination URL is outside the API origin")
            url = path_or_url
        else:
            url = f"{self._base_url}{path_or_url}"
        for attempt in range(3):
            try:
                response = await self._client().request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            except httpx.TimeoutException as exc:
                if attempt == 1:
                    raise GitHubApiError("GitHub API request timed out") from exc
                await self._sleep(2**attempt)
                continue

            if self._is_rate_limited(response):
                if attempt == 2:
                    raise GitHubRateLimited("GitHub API rate limit was exhausted")
                await self._sleep(self._rate_limit_delay(response, attempt))
                continue
            if response.status_code >= 500:
                if attempt == 2:
                    raise GitHubApiError(
                        f"GitHub API failed with status {response.status_code}"
                    )
                await self._sleep(2**attempt)
                continue
            if response.status_code >= 400:
                self._raise_typed_error(response.status_code, error_kind)
            return response
        raise GitHubApiError("GitHub API request failed")

    @staticmethod
    def _is_rate_limited(response: httpx.Response) -> bool:
        return response.status_code == 429 or (
            response.status_code == 403
            and response.headers.get("X-RateLimit-Remaining") == "0"
        )

    @staticmethod
    def _rate_limit_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0)
            except ValueError:
                pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return max(float(reset) - time.time(), 0)
            except ValueError:
                pass
        return float(2**attempt)

    @staticmethod
    def _raise_typed_error(status_code: int, error_kind: str) -> None:
        if error_kind in {"installation", "installation_repositories"} and status_code in {
            401,
            404,
        }:
            raise GitHubInstallationRevoked("GitHub installation is no longer available")
        if error_kind == "branch" and status_code == 404:
            raise GitHubBranchMissing("GitHub branch does not exist")
        if error_kind == "repository" and status_code == 404:
            raise GitHubRepositoryDeleted("GitHub repository no longer exists")
        if error_kind in {
            "installation",
            "repository",
            "access",
            "installation_repositories",
        } and status_code in {401, 403}:
            raise GitHubAccessLost("GitHub repository access was lost")
        raise GitHubApiError(f"GitHub API returned status {status_code}")

    async def get_installation_token(self, installation_id: int) -> str:
        cached = self._token_cache.get(installation_id)
        if cached and cached.expires_at > datetime.now(UTC) + timedelta(minutes=1):
            return cached.value
        response = await self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),
            error_kind="installation_repositories",
        )
        payload = response.json()
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        self._token_cache[installation_id] = CachedInstallationToken(
            value=payload["token"],
            expires_at=expires_at,
        )
        return payload["token"]

    async def get_app(self) -> dict[str, Any]:
        response = await self._request("GET", "/app", token=self._app_jwt())
        return response.json()

    async def get_installation(self, installation_id: int) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/app/installations/{installation_id}",
            token=self._app_jwt(),
            error_kind="installation",
        )
        return response.json()

    async def exchange_user_code(self, code: str) -> str:
        if not self.user_authorization_configured:
            raise GitHubApiError(
                "GitHub user authorization is not configured"
            )
        try:
            response = await self._client().post(
                f"{self._oauth_base_url}/login/oauth/access_token",
                data={
                    "client_id": self._settings.github_client_id,
                    "client_secret": self._settings.github_client_secret,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise GitHubApiError("GitHub user authorization timed out") from exc
        if response.status_code >= 400:
            raise GitHubApiError(
                f"GitHub user authorization returned status {response.status_code}"
            )
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GitHubApiError("GitHub user authorization did not return a token")
        return access_token

    async def list_user_installations(
        self,
        user_access_token: str,
    ) -> list[dict[str, Any]]:
        url = "/user/installations"
        installations: list[dict[str, Any]] = []
        while url:
            response = await self._request(
                "GET",
                url,
                token=user_access_token,
                params={"per_page": 100} if not url.startswith("http") else None,
                error_kind="access",
            )
            payload = response.json()
            page = payload.get("installations") if isinstance(payload, dict) else None
            if not isinstance(page, list):
                raise GitHubApiError(
                    "GitHub user installations returned an unexpected payload"
                )
            installations.extend(page)
            url = response.links.get("next", {}).get("url", "")
        return installations

    async def list_installations(self) -> list[dict[str, Any]]:
        return await self._paginate("/app/installations", token=self._app_jwt())

    async def list_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        token = await self.get_installation_token(installation_id)
        return await self._paginate(
            "/installation/repositories",
            token=token,
            error_kind="installation_repositories",
        )

    async def _paginate(
        self,
        path: str,
        *,
        token: str,
        error_kind: str = "api",
    ) -> list[dict[str, Any]]:
        url = path
        items: list[dict[str, Any]] = []
        while url:
            response = await self._request(
                "GET",
                url,
                token=token,
                params={"per_page": 100} if not url.startswith("http") else None,
                error_kind=error_kind,
            )
            payload = response.json()
            if isinstance(payload, list):
                items.extend(payload)
            elif isinstance(payload, dict):
                envelope = next(
                    (key for key in ("installations", "repositories") if key in payload),
                    None,
                )
                if envelope is None:
                    items.append(payload)
                elif isinstance(payload[envelope], list):
                    items.extend(payload[envelope])
                else:
                    raise GitHubApiError("GitHub API returned an unexpected payload")
            else:
                raise GitHubApiError("GitHub API returned an unexpected payload")
            url = response.links.get("next", {}).get("url", "")
        return items

    async def get_repository(self, installation_id: int, repository_id: int) -> dict[str, Any]:
        token = await self.get_installation_token(installation_id)
        response = await self._request(
            "GET",
            f"/repositories/{repository_id}",
            token=token,
            error_kind="repository",
        )
        return response.json()

    async def get_default_branch(self, installation_id: int, repository_id: int) -> str:
        return (await self.get_repository(installation_id, repository_id))["default_branch"]

    async def list_branches(self, installation_id: int, repository_id: int) -> list[dict[str, Any]]:
        token = await self.get_installation_token(installation_id)
        return await self._paginate(
            f"/repositories/{repository_id}/branches",
            token=token,
            error_kind="access",
        )

    async def get_branch_revision(
        self,
        installation_id: int,
        repository_id: int,
        branch: str,
    ) -> str:
        token = await self.get_installation_token(installation_id)
        response = await self._request(
            "GET",
            f"/repositories/{repository_id}/branches/{quote(branch, safe='')}",
            token=token,
            error_kind="branch",
        )
        return response.json()["commit"]["sha"]

    async def get_repository_tree(
        self,
        installation_id: int,
        repository_id: int,
        tree_sha: str,
    ) -> list[dict[str, Any]]:
        token = await self.get_installation_token(installation_id)
        response = await self._request(
            "GET",
            f"/repositories/{repository_id}/git/trees/{tree_sha}",
            token=token,
            params={"recursive": "1"},
            error_kind="repository",
        )
        payload = response.json()
        if payload.get("truncated"):
            raise GitHubApiError("GitHub repository tree response was truncated")
        return payload["tree"]

    async def get_blob_content(
        self,
        installation_id: int,
        repository_id: int,
        blob_sha: str,
    ) -> bytes:
        token = await self.get_installation_token(installation_id)
        response = await self._request(
            "GET",
            f"/repositories/{repository_id}/git/blobs/{blob_sha}",
            token=token,
            error_kind="repository",
        )
        payload = response.json()
        if payload.get("encoding") != "base64":
            raise GitHubApiError("GitHub blob response did not use base64 encoding")
        encoded = "".join(payload["content"].split())
        return base64.b64decode(encoded, validate=True)

    async def get_blob_prefix(
        self,
        installation_id: int,
        repository_id: int,
        blob_sha: str,
        max_bytes: int,
    ) -> bytes:
        if max_bytes <= 0:
            return b""
        token = await self.get_installation_token(installation_id)
        url = f"{self._base_url}/repositories/{repository_id}/git/blobs/{blob_sha}"
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        for attempt in range(3):
            try:
                async with self._client().stream("GET", url, headers=headers) as response:
                    if self._is_rate_limited(response):
                        if attempt == 2:
                            raise GitHubRateLimited("GitHub API rate limit was exhausted")
                        delay = self._rate_limit_delay(response, attempt)
                    elif response.status_code >= 500:
                        if attempt == 2:
                            raise GitHubApiError(
                                f"GitHub API failed with status {response.status_code}"
                            )
                        delay = float(2**attempt)
                    else:
                        if response.status_code >= 400:
                            self._raise_typed_error(response.status_code, "repository")
                        if response.status_code not in {200, 206}:
                            raise GitHubApiError(
                                "GitHub raw blob request returned an unexpected status"
                            )
                        parts: list[bytes] = []
                        remaining = max_bytes
                        async for chunk in response.aiter_bytes():
                            parts.append(chunk[:remaining])
                            remaining -= min(len(chunk), remaining)
                            if remaining == 0:
                                break
                        return b"".join(parts)
            except httpx.TimeoutException as exc:
                if attempt == 1:
                    raise GitHubApiError("GitHub API request timed out") from exc
                delay = float(2**attempt)
            await self._sleep(delay)
        raise GitHubApiError("GitHub API request failed")

    async def get_file_content(
        self,
        installation_id: int,
        repository_id: int,
        path: str,
        ref: str,
    ) -> bytes:
        token = await self.get_installation_token(installation_id)
        response = await self._request(
            "GET",
            f"/repositories/{repository_id}/contents/{quote(path, safe='/')}",
            token=token,
            params={"ref": ref},
            error_kind="repository",
        )
        payload = response.json()
        if payload.get("encoding") != "base64":
            raise GitHubApiError("GitHub content response did not use base64 encoding")
        encoded = "".join(payload["content"].split())
        return base64.b64decode(encoded, validate=True)
