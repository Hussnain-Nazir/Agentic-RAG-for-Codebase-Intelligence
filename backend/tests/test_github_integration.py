import asyncio
import base64
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.github import get_github_client
from app.api.routes.repositories import get_embedding_provider
from app.auth.security import create_access_token
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.github.client import GitHubClient
from app.github.errors import (
    GitHubAccessLost,
    GitHubApiError,
    GitHubBranchMissing,
    GitHubInstallationRevoked,
    GitHubRateLimited,
    GitHubRepositoryDeleted,
)
from app.main import create_app
from app.models import (
    GitHubInstallation,
    GitHubInstallationStatus,
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositorySourceType,
    User,
)
from app.sources.github import GitHubRepositorySource

TEST_SECRET = "phase-six-test-secret-at-least-32-bytes"
FUTURE_EXPIRY = "2099-01-01T00:00:00Z"


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]


async def no_sleep(delay: float) -> None:
    del delay


def github_client(handler: Any) -> GitHubClient:
    client = GitHubClient(
        Settings(
            github_app_id="12345",
            github_app_private_key_path="unused-in-mocked-tests.pem",
            github_client_id="test-client-id",
            github_client_secret="test-client-secret",
        ),
        base_url="https://api.github.test",
        oauth_base_url="https://github.test",
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )
    client._app_jwt = lambda: "test-app-jwt"  # type: ignore[method-assign]
    return client


def token_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        201,
        json={"token": "test-installation-token", "expires_at": FUTURE_EXPIRY},
        request=request,
    )


def test_installation_token_is_retrieved_and_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer test-app-jwt"
        return token_response(request)

    client = github_client(handler)

    first = asyncio.run(client.get_installation_token(77))
    second = asyncio.run(client.get_installation_token(77))

    assert first == second == "test-installation-token"
    assert calls == 1


def test_repository_listing_follows_link_header_pagination() -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        requested_pages.append(str(request.url))
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json={"repositories": [{"id": 2, "name": "second"}]},
                request=request,
            )
        return httpx.Response(
            200,
            json={"repositories": [{"id": 1, "name": "first"}]},
            headers={
                "Link": '<https://api.github.test/installation/repositories?page=2>; rel="next"'
            },
            request=request,
        )

    repositories = asyncio.run(github_client(handler).list_repositories(77))

    assert [repository["id"] for repository in repositories] == [1, 2]
    assert len(requested_pages) == 2


def test_pagination_rejects_external_link_before_sending_installation_credential() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        return httpx.Response(
            200,
            json={"repositories": [{"id": 1}]},
            headers={"Link": '<https://other.example.invalid/collect>; rel="next"'},
            request=request,
        )

    with pytest.raises(GitHubApiError, match="outside the API origin"):
        asyncio.run(github_client(handler).list_repositories(77))
    assert requested_paths == [
        "/app/installations/77/access_tokens",
        "/installation/repositories",
    ]


def test_app_installation_listing_flattens_enveloped_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"installations": [{"id": 2}]}, request=request)
        return httpx.Response(
            200,
            json={"installations": [{"id": 1}]},
            headers={"Link": '<https://api.github.test/app/installations?page=2>; rel="next"'},
            request=request,
        )

    assert asyncio.run(github_client(handler).list_installations()) == [
        {"id": 1}, {"id": 2}
    ]


def test_installation_repository_listing_maps_non_rate_limited_403_to_access_lost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        return httpx.Response(403, request=request)

    with pytest.raises(GitHubAccessLost):
        asyncio.run(github_client(handler).list_repositories(77))


def test_github_client_reuses_and_closes_one_http_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1}, request=request)

    async def exercise() -> None:
        client = github_client(handler)
        await client.get_app()
        http_client = client._http_client
        await client.get_app()
        assert client._http_client is http_client
        await client.aclose()
        assert http_client is not None and http_client.is_closed

    asyncio.run(exercise())


def test_app_shutdown_closes_cached_github_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.routes.github as github_routes

    monkeypatch.setattr(github_routes, "_CLIENTS", {})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1}, request=request)

    github = github_client(handler)
    asyncio.run(github.get_app())
    http_client = github._http_client
    github_routes._CLIENTS[("test", "test", "test")] = github
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, jwt_secret=TEST_SECRET
    )
    with TestClient(app):
        pass

    assert http_client is not None and http_client.is_closed
    assert github_routes._CLIENTS == {}


def test_branch_and_content_paths_are_percent_encoded() -> None:
    paths: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        paths.append(request.url.raw_path)
        if "/branches/" in request.url.path:
            return httpx.Response(200, json={"commit": {"sha": "revision"}}, request=request)
        return httpx.Response(
            200,
            json={"encoding": "base64", "content": base64.b64encode(b"ok").decode()},
            request=request,
        )

    async def exercise() -> None:
        client = github_client(handler)
        await client.get_branch_revision(77, 1001, "feature/#? %")
        await client.get_file_content(77, 1001, "dir/a #?%.py", "main")
        await client.aclose()

    asyncio.run(exercise())
    assert b"feature%2F%23%3F%20%25" in paths[0]
    assert b"dir/a%20%23%3F%25.py" in paths[1]


def test_installation_revoked_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    with pytest.raises(GitHubInstallationRevoked):
        asyncio.run(github_client(handler).get_installation_token(77))


@pytest.mark.parametrize(
    ("status_code", "method_name", "expected_error"),
    [
        (403, "repository", GitHubAccessLost),
        (404, "repository", GitHubRepositoryDeleted),
        (404, "branch", GitHubBranchMissing),
    ],
)
def test_repository_typed_errors(
    status_code: int,
    method_name: str,
    expected_error: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        return httpx.Response(status_code, request=request)

    client = github_client(handler)
    with pytest.raises(expected_error):
        if method_name == "branch":
            asyncio.run(client.get_branch_revision(77, 1001, "missing"))
        else:
            asyncio.run(client.get_repository(77, 1001))


def test_rate_limit_retries_three_times_then_raises() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        attempts += 1
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "0"},
            request=request,
        )

    with pytest.raises(GitHubRateLimited):
        asyncio.run(github_client(handler).get_repository(77, 1001))
    assert attempts == 3


def test_server_error_retries_three_times_then_raises_api_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        attempts += 1
        return httpx.Response(503, request=request)

    with pytest.raises(GitHubApiError):
        asyncio.run(github_client(handler).get_repository(77, 1001))
    assert attempts == 3


def test_blob_content_decodes_github_base64_with_line_breaks() -> None:
    expected = b"repository content"
    encoded = base64.b64encode(expected).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        return httpx.Response(
            200,
            json={"encoding": "base64", "content": f"{encoded[:8]}\n{encoded[8:]}"},
            request=request,
        )

    content = asyncio.run(github_client(handler).get_blob_content(77, 1001, "sha"))
    assert content == expected


def test_blob_prefix_uses_raw_response_and_returns_bounded_bytes() -> None:
    payload = b"a" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        assert request.headers["Accept"] == "application/vnd.github.raw+json"
        return httpx.Response(200, content=payload, request=request)

    async def exercise() -> bytes:
        client = github_client(handler)
        prefix = await client.get_blob_prefix(77, 1001, "sha", 8192)
        await client.aclose()
        return prefix

    prefix = asyncio.run(exercise())
    assert prefix == payload[:8192]


def test_blob_prefix_rejects_redirect_without_treating_it_as_file_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response(request)
        return httpx.Response(302, headers={"Location": "https://other.example.invalid/blob"}, request=request)

    with pytest.raises(GitHubApiError, match="unexpected status"):
        asyncio.run(github_client(handler).get_blob_prefix(77, 1001, "sha", 8192))


def test_user_authorization_exchanges_code_and_lists_installations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            assert request.headers["Accept"] == "application/json"
            assert b"client_secret=test-client-secret" in request.content
            return httpx.Response(
                200,
                json={"access_token": "test-user-token"},
                request=request,
            )
        assert request.url.path == "/user/installations"
        assert request.headers["Authorization"] == "Bearer test-user-token"
        return httpx.Response(
            200,
            json={"installations": [{"id": 77}]},
            request=request,
        )

    client = github_client(handler)
    user_token = asyncio.run(client.exchange_user_code("oauth-code"))
    installations = asyncio.run(client.list_user_installations(user_token))

    assert user_token == "test-user-token"
    assert installations == [{"id": 77}]


class FakeGitHubClient:
    blobs = {
        "sha-app": b'def hello() -> str:\n    return "hello"\n',
        "sha-readme": b"# Fixture repository\n",
    }
    user_authorization_configured = True

    async def get_app(self) -> dict[str, Any]:
        return {"html_url": "https://github.com/apps/prism-test"}

    async def get_installation_token(self, installation_id: int) -> str:
        assert installation_id == 77
        return "test-installation-token"

    async def get_installation(self, installation_id: int) -> dict[str, Any]:
        assert installation_id == 77
        return {"id": 77, "account": {"login": "example"}}

    async def exchange_user_code(self, code: str) -> str:
        assert code == "test-oauth-code"
        return "test-user-token"

    async def list_user_installations(
        self,
        user_access_token: str,
    ) -> list[dict[str, Any]]:
        assert user_access_token == "test-user-token"
        return [{"id": 77, "account": {"login": "example"}}]

    async def list_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        assert installation_id == 77
        return [
            {
                "id": 1001,
                "name": "fixture",
                "full_name": "example/fixture",
                "default_branch": "main",
                "private": True,
            }
        ]

    async def get_branch_revision(
        self,
        installation_id: int,
        repository_id: int,
        branch: str,
    ) -> str:
        assert (installation_id, repository_id, branch) == (77, 1001, "main")
        return "commit-sha"

    async def get_repository_tree(
        self,
        installation_id: int,
        repository_id: int,
        tree_sha: str,
    ) -> list[dict[str, Any]]:
        assert (installation_id, repository_id, tree_sha) == (77, 1001, "commit-sha")
        return [
            {"path": "README.md", "type": "blob", "sha": "sha-readme", "size": 21},
            {"path": "app.py", "type": "blob", "sha": "sha-app", "size": 42},
        ]

    async def get_blob_content(
        self,
        installation_id: int,
        repository_id: int,
        blob_sha: str,
    ) -> bytes:
        assert (installation_id, repository_id) == (77, 1001)
        return self.blobs[blob_sha]


def test_github_source_pins_revision_and_applies_root_gitignore() -> None:
    class ChangingClient:
        def __init__(self) -> None:
            self.revision_calls = 0
            self.tree_revisions: list[str] = []
            self.blob_calls: list[str] = []
            self.blobs = {
                "ignore-sha": b"ignored.py\n",
                "kept-sha": b"value = 1\n",
                "excluded-sha": b"ignored = 1\n",
            }

        async def get_branch_revision(self, installation_id, repository_id, ref):
            del installation_id, repository_id, ref
            self.revision_calls += 1
            return f"revision-{self.revision_calls}"

        async def get_repository_tree(self, installation_id, repository_id, revision):
            del installation_id, repository_id
            self.tree_revisions.append(revision)
            return [
                {"path": ".gitignore", "type": "blob", "sha": "ignore-sha", "size": 11},
                {"path": "ignored.py", "type": "blob", "sha": "excluded-sha", "size": 12},
                {"path": "kept.py", "type": "blob", "sha": "kept-sha", "size": 10},
                {"path": ".env", "type": "blob", "sha": "secret-sha", "size": 5},
            ]

        async def get_blob_content(self, installation_id, repository_id, blob_sha):
            del installation_id, repository_id
            self.blob_calls.append(blob_sha)
            return self.blobs[blob_sha]

    async def exercise() -> None:
        client = ChangingClient()
        source = GitHubRepositorySource(client, 77, 1001)
        revision = await source.get_revision("main")
        files = await source.list_files("main")
        assert revision == "revision-1"
        assert client.revision_calls == 1
        assert client.tree_revisions == [revision]
        assert [item.path for item in files] == [".gitignore", "kept.py"]
        assert await source.get_file_prefix("main", "kept.py", 4) == b"valu"
        assert await source.get_file_content("main", "kept.py") == b"value = 1\n"
        assert client.blob_calls == ["ignore-sha", "kept-sha"]

    asyncio.run(exercise())


@pytest.fixture
def github_import_context() -> Iterator[
    tuple[TestClient, async_sessionmaker[AsyncSession], uuid.UUID]
]:
    database_url = "sqlite+aiosqlite://"
    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email="github-import@example.com",
                    hashed_password="unused",
                )
            )
            session.add(
                GitHubInstallation(
                    user_id=user_id,
                    installation_id=77,
                    account_login="example",
                    status=GitHubInstallationStatus.ACTIVE,
                )
            )
            await session.commit()

    asyncio.run(prepare_database())

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_get_settings() -> Settings:
        return Settings(
            database_url=database_url,
            jwt_secret=TEST_SECRET,
            github_client_id="test-client-id",
            github_client_secret="test-client-secret",
            github_callback_success_url="http://localhost:5173/?github=connected",
        )

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_github_client] = FakeGitHubClient
    app.dependency_overrides[get_embedding_provider] = FakeEmbeddingProvider
    with TestClient(app) as client:
        yield client, session_factory, user_id
    asyncio.run(engine.dispose())


def test_github_import_uses_shared_normalization_and_persists_blob_shas(
    github_import_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
    ],
) -> None:
    client, session_factory, user_id = github_import_context
    response = client.post(
        "/repositories",
        headers={
            "Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"
        },
        json={"source_type": "github", "github_repo_id": 1001, "branch": "main"},
    )

    assert response.status_code == 201
    assert response.json()["state"] == "READY"
    assert response.json()["size_warning"] is False

    async def inspect() -> None:
        async with session_factory() as session:
            repository = await session.scalar(select(Repository))
            index = await session.scalar(select(RepositoryIndex))
            files = list(
                await session.scalars(
                    select(RepositoryFile).order_by(RepositoryFile.path)
                )
            )
            assert repository is not None
            assert repository.source_type is RepositorySourceType.GITHUB
            assert repository.github_repo_id == 1001
            assert index is not None
            assert index.revision == "commit-sha"
            assert [item.path for item in files] == ["README.md", "app.py"]
            assert [item.github_sha for item in files] == ["sha-readme", "sha-app"]
            assert all(item.status is RepositoryFileStatus.OK for item in files)

    asyncio.run(inspect())


def test_github_routes_persist_and_list_installation_and_repositories(
    github_import_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
    ],
) -> None:
    client, session_factory, user_id = github_import_context
    headers = {
        "Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"
    }

    async def remove_seed_installation() -> None:
        async with session_factory() as session:
            installation = await session.scalar(select(GitHubInstallation))
            assert installation is not None
            await session.delete(installation)
            await session.commit()

    asyncio.run(remove_seed_installation())

    install_url = client.get("/github/install-url", headers=headers)
    state = parse_qs(urlparse(install_url.json()["url"]).query)["state"][0]
    callback = client.get(
        (
            "/github/callback?installation_id=77&setup_action=install"
            f"&code=test-oauth-code&state={state}"
        ),
        follow_redirects=False,
    )
    installations = client.get("/github/installations", headers=headers)

    assert install_url.status_code == 200
    assert install_url.json()["url"].startswith(
        "https://github.com/apps/prism-test/installations/new?state="
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:5173/?github=connected"
    assert installations.status_code == 200
    assert installations.json()[0]["installation_id"] == 77

    async def get_installation_id() -> uuid.UUID:
        async with session_factory() as session:
            installation = await session.scalar(select(GitHubInstallation))
            assert installation is not None
            return installation.id

    installation_id = asyncio.run(get_installation_id())
    repositories = client.get(
        f"/github/installations/{installation_id}/repositories",
        headers=headers,
    )
    assert repositories.status_code == 200
    assert repositories.json() == [
        {
            "id": 1001,
            "name": "fixture",
            "full_name": "example/fixture",
            "default_branch": "main",
            "private": True,
        }
    ]

    replay = client.get(
        (
            "/github/callback?installation_id=77&setup_action=install"
            f"&code=test-oauth-code&state={state}"
        ),
        follow_redirects=False,
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "Invalid or reused GitHub state"


def test_github_callback_rejects_missing_or_unknown_state(
    github_import_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
    ],
) -> None:
    client, _, _ = github_import_context

    missing = client.get(
        "/github/callback?installation_id=77&code=test-oauth-code",
        follow_redirects=False,
    )
    unknown = client.get(
        (
            "/github/callback?installation_id=77&code=test-oauth-code"
            "&state=unknown-state"
        ),
        follow_redirects=False,
    )

    assert missing.status_code == 400
    assert unknown.status_code == 400


def test_install_url_maps_github_app_error_to_502(github_import_context) -> None:
    client, _, user_id = github_import_context

    class FailingAppClient(FakeGitHubClient):
        async def get_app(self):
            raise GitHubApiError("GitHub App unavailable")

    client.app.dependency_overrides[get_github_client] = FailingAppClient
    response = client.get(
        "/github/install-url",
        headers={"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"},
    )
    assert response.status_code == 502


def test_repeated_github_import_returns_stable_conflict(github_import_context) -> None:
    client, session_factory, user_id = github_import_context
    headers = {"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"}
    payload = {"source_type": "github", "github_repo_id": 1001, "branch": "main"}

    first = client.post("/repositories", headers=headers, json=payload)
    second = client.post("/repositories", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "Repository is already imported"

    async def repository_count() -> int:
        async with session_factory() as session:
            return len(list(await session.scalars(select(Repository))))

    assert asyncio.run(repository_count()) == 1


def test_revoked_first_installation_does_not_block_later_import(github_import_context) -> None:
    client, session_factory, user_id = github_import_context

    async def seed_second_installation_and_existing_repository() -> uuid.UUID:
        async with session_factory() as session:
            first = await session.scalar(select(GitHubInstallation))
            assert first is not None
            second = GitHubInstallation(
                user_id=user_id, installation_id=88, account_login="second"
            )
            session.add(second)
            session.add(
                Repository(
                    owner_id=user_id,
                    github_installation_id=first.id,
                    source_type=RepositorySourceType.GITHUB,
                    github_repo_id=2002,
                    name="prior",
                    default_branch="main",
                    selected_branch="main",
                    access_status=RepositoryAccessStatus.ACTIVE,
                )
            )
            await session.commit()
            return first.id

    first_id = asyncio.run(seed_second_installation_and_existing_repository())

    class RevokedFirstClient(FakeGitHubClient):
        async def list_repositories(self, installation_id):
            if installation_id == 77:
                raise GitHubInstallationRevoked("Installation revoked")
            assert installation_id == 88
            return [{
                "id": 1001, "name": "fixture", "default_branch": "main",
                "full_name": "example/fixture", "private": True,
            }]

        async def get_branch_revision(self, installation_id, repository_id, branch):
            assert (installation_id, repository_id, branch) == (88, 1001, "main")
            return "commit-sha"

        async def get_repository_tree(self, installation_id, repository_id, revision):
            assert (installation_id, repository_id, revision) == (88, 1001, "commit-sha")
            return [{"path": "app.py", "type": "blob", "sha": "sha-app", "size": 42}]

        async def get_blob_content(self, installation_id, repository_id, blob_sha):
            assert (installation_id, repository_id) == (88, 1001)
            return self.blobs[blob_sha]

    client.app.dependency_overrides[get_github_client] = RevokedFirstClient
    response = client.post(
        "/repositories",
        headers={"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"},
        json={"source_type": "github", "github_repo_id": 1001, "branch": "main"},
    )
    assert response.status_code == 201

    async def inspect() -> None:
        async with session_factory() as session:
            first = await session.get(GitHubInstallation, first_id)
            prior = await session.scalar(
                select(Repository).where(Repository.github_repo_id == 2002)
            )
            assert first is not None and first.status is GitHubInstallationStatus.REVOKED
            assert prior is not None and prior.access_status is RepositoryAccessStatus.ACCESS_LOST

    asyncio.run(inspect())


def test_listing_access_loss_marks_existing_repository(github_import_context) -> None:
    client, session_factory, user_id = github_import_context

    async def seed_repository() -> None:
        async with session_factory() as session:
            installation = await session.scalar(select(GitHubInstallation))
            assert installation is not None
            session.add(
                Repository(
                    owner_id=user_id,
                    github_installation_id=installation.id,
                    source_type=RepositorySourceType.GITHUB,
                    github_repo_id=2002,
                    name="prior",
                    default_branch="main",
                    selected_branch="main",
                    access_status=RepositoryAccessStatus.ACTIVE,
                )
            )
            await session.commit()

    asyncio.run(seed_repository())

    class AccessLostClient(FakeGitHubClient):
        async def list_repositories(self, installation_id):
            del installation_id
            raise GitHubAccessLost("Installation repository access lost")

    client.app.dependency_overrides[get_github_client] = AccessLostClient
    response = client.post(
        "/repositories",
        headers={"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"},
        json={"source_type": "github", "github_repo_id": 1001, "branch": "main"},
    )
    assert response.status_code == 404

    async def access_status() -> RepositoryAccessStatus:
        async with session_factory() as session:
            repository = await session.scalar(select(Repository))
            assert repository is not None
            return repository.access_status

    assert asyncio.run(access_status()) is RepositoryAccessStatus.ACCESS_LOST


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [
        (GitHubInstallationRevoked, 401),
        (GitHubAccessLost, 403),
        (GitHubRepositoryDeleted, 404),
        (GitHubBranchMissing, 404),
        (GitHubRateLimited, 429),
        (GitHubApiError, 502),
    ],
)
def test_github_import_maps_typed_source_failures(
    github_import_context, error_type: type[Exception], expected_status: int
) -> None:
    client, session_factory, user_id = github_import_context

    class FailingSourceClient(FakeGitHubClient):
        async def get_branch_revision(self, installation_id, repository_id, branch):
            del installation_id, repository_id, branch
            raise error_type("GitHub source unavailable")

    client.app.dependency_overrides[get_github_client] = FailingSourceClient
    response = client.post(
        "/repositories",
        headers={"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"},
        json={"source_type": "github", "github_repo_id": 1001, "branch": "main"},
    )
    assert response.status_code == expected_status

    if error_type is GitHubInstallationRevoked:
        async def status() -> GitHubInstallationStatus:
            async with session_factory() as session:
                installation = await session.scalar(select(GitHubInstallation))
                assert installation is not None
                return installation.status

        assert asyncio.run(status()) is GitHubInstallationStatus.REVOKED
