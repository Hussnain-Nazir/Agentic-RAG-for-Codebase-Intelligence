import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_repository_or_404
from app.auth.security import create_access_token
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import (
    GitHubInstallation,
    GitHubInstallationStatus,
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.sources.base import RepositorySource
from app.sources.github import GitHubRepositorySource

TEST_SECRET = "phase-two-test-secret-at-least-32-bytes"


@pytest.fixture
def repository_context() -> Iterator[
    tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
    ]
]:
    database_url = "sqlite+aiosqlite://"
    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    repository_id = uuid.uuid4()

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add_all(
                [
                    User(
                        id=owner_id,
                        email="owner@example.com",
                        hashed_password="not-used-in-this-test",
                    ),
                    User(
                        id=other_user_id,
                        email="other@example.com",
                        hashed_password="not-used-in-this-test",
                    ),
                    Repository(
                        id=repository_id,
                        owner_id=owner_id,
                        source_type=RepositorySourceType.UPLOAD,
                        name="fixture",
                        default_branch="main",
                        selected_branch="main",
                        access_status=RepositoryAccessStatus.ACTIVE,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(prepare_database())

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_get_settings() -> Settings:
        return Settings(database_url=database_url, jwt_secret=TEST_SECRET)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    @app.get("/repository-test/{repository_id}")
    async def repository_test(
        repository: Repository = Depends(get_repository_or_404),
    ) -> dict[str, str]:
        return {"repository_id": str(repository.id)}

    with TestClient(app) as client:
        yield client, session_factory, owner_id, other_user_id, repository_id

    asyncio.run(engine.dispose())


def authorization_header(user_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(user_id, TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


def test_model_creation_and_relationships() -> None:
    database_url = "sqlite+aiosqlite://"
    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def exercise_models() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(email="models@example.com", hashed_password="hash")
            installation = GitHubInstallation(
                installation_id=123456789012,
                account_login="example",
                status=GitHubInstallationStatus.ACTIVE,
            )
            repository = Repository(
                source_type=RepositorySourceType.GITHUB,
                github_repo_id=987654321012,
                name="example/repository",
                default_branch="main",
                selected_branch="main",
                access_status=RepositoryAccessStatus.ACTIVE,
            )
            repository_index = RepositoryIndex(
                version=1,
                revision="revision-sha",
                state=RepositoryIndexState.PENDING,
            )
            repository_file = RepositoryFile(
                path="backend/app/main.py",
                language="python",
                github_sha="blob-sha",
                content_hash="content-hash",
                status=RepositoryFileStatus.OK,
                size_bytes=128,
            )

            user.github_installations.append(installation)
            user.repositories.append(repository)
            installation.repositories.append(repository)
            repository.indexes.append(repository_index)
            repository_index.files.append(repository_file)
            session.add(user)
            await session.commit()

            assert repository.owner is user
            assert repository.github_installation is installation
            assert repository_index.repository is repository
            assert repository_file.repository_index is repository_index

    asyncio.run(exercise_models())
    asyncio.run(engine.dispose())


def test_repository_index_state_values() -> None:
    assert [state.value for state in RepositoryIndexState] == [
        "PENDING",
        "DISCOVERING",
        "PARSING",
        "EMBEDDING",
        "INDEXING",
        "READY",
        "FAILED",
        "PARTIAL",
    ]


def test_repository_dependency_returns_404(
    repository_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
    ],
) -> None:
    client, _, owner_id, _, _ = repository_context
    response = client.get(
        f"/repository-test/{uuid.uuid4()}",
        headers=authorization_header(owner_id),
    )
    assert response.status_code == 404


def test_repository_dependency_returns_403_for_wrong_owner(
    repository_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
    ],
) -> None:
    client, _, _, other_user_id, repository_id = repository_context
    response = client.get(
        f"/repository-test/{repository_id}",
        headers=authorization_header(other_user_id),
    )
    assert response.status_code == 403


def test_repository_dependency_returns_repository_for_owner(
    repository_context: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        uuid.UUID,
        uuid.UUID,
        uuid.UUID,
    ],
) -> None:
    client, _, owner_id, _, repository_id = repository_context
    response = client.get(
        f"/repository-test/{repository_id}",
        headers=authorization_header(owner_id),
    )
    assert response.status_code == 200
    assert response.json() == {"repository_id": str(repository_id)}


def test_github_source_stub_enforces_not_implemented() -> None:
    source: RepositorySource = GitHubRepositorySource()
    async def call_methods() -> None:
        with pytest.raises(NotImplementedError, match="not implemented"):
            await source.list_files("main")
        with pytest.raises(NotImplementedError, match="not implemented"):
            await source.get_file_content("main", "app.py")
        with pytest.raises(NotImplementedError, match="not implemented"):
            await source.get_revision("main")

    asyncio.run(call_methods())
