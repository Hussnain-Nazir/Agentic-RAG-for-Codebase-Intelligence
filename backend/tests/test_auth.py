import asyncio
from collections.abc import AsyncIterator, Iterator
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.user import User

TEST_EMAIL = "developer@example.com"
TEST_PASSWORD = "correct-password"
TEST_SECRET = "test-only-jwt-secret-at-least-32-bytes"


@pytest.fixture
def auth_context() -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    database_url = "sqlite+aiosqlite://"
    engine = create_async_engine(
        database_url,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_get_settings() -> Settings:
        return Settings(
            database_url=database_url,
            jwt_secret=TEST_SECRET,
        )

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    @app.get("/protected-test")
    async def protected_test(user: User = Depends(get_current_user)) -> dict[str, str]:
        return {"user_id": str(user.id)}

    with TestClient(app) as client:
        yield client, session_factory

    asyncio.run(engine.dispose())


def register(client: TestClient) -> str:
    response = client.post(
        "/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["user_id"]


def test_successful_registration_hashes_password(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = auth_context
    user_id = register(client)

    async def load_user() -> User:
        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.email == TEST_EMAIL))
            assert user is not None
            return user

    stored_user = asyncio.run(load_user())
    assert str(stored_user.id) == user_id
    assert stored_user.hashed_password != TEST_PASSWORD
    assert stored_user.hashed_password.startswith("$2")


def test_duplicate_email_is_rejected(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = auth_context
    register(client)

    response = client.post(
        "/auth/register",
        json={"email": TEST_EMAIL.upper(), "password": TEST_PASSWORD},
    )

    assert response.status_code == 409


def test_successful_login(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = auth_context
    register(client)

    response = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )

    assert response.status_code == 200
    assert isinstance(response.json()["access_token"], str)


def test_invalid_password_is_rejected(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = auth_context
    register(client)

    response = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_protected_route_rejects_missing_token(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = auth_context

    response = client.get("/protected-test")

    assert response.status_code == 401


def test_protected_route_accepts_valid_token(
    auth_context: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _ = auth_context
    user_id = register(client)
    login_response = client.post(
        "/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/protected-test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": user_id}
