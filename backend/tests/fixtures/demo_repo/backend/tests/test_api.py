import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_app.db import Base  # noqa: E402
from demo_app.main import create_app  # noqa: E402
from demo_app.models import Organization  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(Organization(name="Example"))
        db.commit()
    with TestClient(create_app(factory, "demo-test-secret")) as test_client:
        yield test_client
    engine.dispose()


def register_and_login(client: TestClient, email: str) -> dict[str, str]:
    created = client.post("/auth/register", json={"email": email, "password": "password123", "organization_id": 1})
    assert created.status_code == 201
    logged_in = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert logged_in.status_code == 200
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


def test_login_and_crud_owner_boundary(client: TestClient) -> None:
    first = register_and_login(client, "one@example.com")
    second = register_and_login(client, "two@example.com")
    assert client.get("/items").status_code in (401, 403)
    created = client.post("/items", json={"title": "First"}, headers=first)
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert [item["title"] for item in client.get("/items", headers=first).json()] == ["First"]
    assert client.get("/items", headers=second).json() == []
    assert client.put(f"/items/{item_id}", json={"title": "Changed"}, headers=second).status_code == 403
    assert client.delete(f"/items/{item_id}", headers=second).status_code == 403
    assert client.put(f"/items/{item_id}", json={"title": "Changed"}, headers=first).json()["title"] == "Changed"
    assert client.delete(f"/items/{item_id}", headers=first).status_code == 204
    assert client.get("/items", headers=first).json() == []


def test_invalid_credentials_and_missing_organization(client: TestClient) -> None:
    missing = client.post("/auth/register", json={"email": "nobody@example.com", "password": "password123", "organization_id": 999})
    assert missing.status_code == 404
    register_and_login(client, "one@example.com")
    assert client.post("/auth/login", json={"email": "one@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/auth/register", json={"email": "one@example.com", "password": "password123", "organization_id": 1}).status_code == 409
