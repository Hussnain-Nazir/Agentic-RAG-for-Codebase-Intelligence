import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import create_access_token
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.llm.base import Message
from app.llm.factory import get_model_a, get_model_b
from app.llm.mock import MockProvider
from app.llm.openai_compatible import (
    LLMProviderRequestError,
    OpenAICompatibleProvider,
    _strict_json_schema,
)
from app.main import create_app
from app.models.user import User

TEST_SECRET = "phase-three-test-secret-at-least-32-bytes"


class StructuredAnswer(BaseModel):
    answer: str
    confidence: str


class StructuredDetail(BaseModel):
    message: str


class Evidence(BaseModel):
    evidence_id: str
    relationship_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    external_source_metadata: dict[str, Any] | None = None


class NestedAnswer(BaseModel):
    detail: StructuredDetail
    evidence: list[Evidence]


def test_strict_transport_schema_closes_nested_objects_and_omits_metadata_maps() -> None:
    schema = _strict_json_schema(NestedAnswer.model_json_schema())

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["StructuredDetail"]["additionalProperties"] is False
    evidence_schema = schema["$defs"]["Evidence"]
    assert evidence_schema["additionalProperties"] is False
    assert set(evidence_schema["properties"]) == {"evidence_id"}
    assert evidence_schema["required"] == ["evidence_id"]


def test_mock_provider_returns_canned_responses_in_order() -> None:
    provider = MockProvider(canned_responses=["first", "second"])
    messages = [Message(role="user", content="question")]

    first = asyncio.run(provider.complete(messages, None, 10))
    second = asyncio.run(provider.complete(messages, None, 10))

    assert first.content == "first"
    assert second.content == "second"
    assert first.input_tokens == 0
    assert first.output_tokens == 0
    assert first.latency_ms == 0


def test_mock_provider_returns_schema_valid_content() -> None:
    provider = MockProvider(
        canned_responses=[{"answer": "known response", "confidence": "high"}]
    )

    result = asyncio.run(
        provider.complete(
            [Message(role="user", content="question")],
            StructuredAnswer,
            10,
        )
    )

    assert StructuredAnswer.model_validate_json(result.content) == StructuredAnswer(
        answer="known response",
        confidence="high",
    )


def test_mock_provider_callback_receives_messages_and_schema() -> None:
    def callback(
        messages: list[Message],
        schema: type[BaseModel] | None,
    ) -> dict[str, str]:
        assert messages == [Message(role="user", content="callback question")]
        assert schema is StructuredAnswer
        return {"answer": "callback response", "confidence": "medium"}

    provider = MockProvider(callback=callback)
    result = asyncio.run(
        provider.complete(
            [Message(role="user", content="callback question")],
            StructuredAnswer,
            10,
        )
    )

    assert json.loads(result.content) == {
        "answer": "callback response",
        "confidence": "medium",
    }


def test_openai_compatible_provider_uses_mock_transport() -> None:
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["authorization"] = request.headers.get("Authorization")
        captured_request["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "test-response",
                "choices": [
                    {"message": {"role": "assistant", "content": "mocked HTTP response"}}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
            },
        )

    provider = OpenAICompatibleProvider(
        name="test-model",
        base_url="https://models.test.invalid/v1",
        api_key="test-api-key",
        timeout_s=30,
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        provider.complete(
            [Message(role="system", content="system instruction"), Message(role="user", content="question")],
            NestedAnswer,
            15,
        )
    )

    assert result.content == "mocked HTTP response"
    assert result.input_tokens == 11
    assert result.output_tokens == 4
    assert captured_request["url"] == "https://models.test.invalid/v1/chat/completions"
    assert captured_request["authorization"] == "Bearer test-api-key"
    payload = captured_request["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "test-model"
    transport_schema = payload["response_format"]["json_schema"]
    assert transport_schema["name"] == "NestedAnswer"
    assert transport_schema["schema"]["additionalProperties"] is False
    assert transport_schema["schema"]["$defs"]["StructuredDetail"]["additionalProperties"] is False
    assert set(transport_schema["schema"]["$defs"]["Evidence"]["properties"]) == {
        "evidence_id"
    }


def test_strict_transport_schema_excludes_application_owned_evidence_metadata() -> None:
    from app.schemas.responses import FlowTraceResponse

    schema = _strict_json_schema(FlowTraceResponse.model_json_schema())
    evidence = schema["$defs"]["Evidence"]

    assert "relationship_metadata" not in evidence["properties"]
    assert "retrieval_metadata" not in evidence["properties"]
    assert "external_source_metadata" not in evidence["properties"]
    assert "relationship_metadata" not in evidence["required"]


def test_openai_compatible_provider_sanitizes_provider_error_details() -> None:
    secret = "test-provider-secret"
    base_url = "https://models.test.invalid/v1"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        f"schema rejected; key={secret}; endpoint={base_url}"
                    )
                }
            },
        )

    provider = OpenAICompatibleProvider(
        name="test-model",
        base_url=base_url,
        api_key=secret,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderRequestError) as exc_info:
        asyncio.run(
            provider.complete(
                [Message(role="user", content="question")],
                StructuredAnswer,
                10,
            )
        )

    assert "schema rejected" in exc_info.value.safe_message
    assert secret not in exc_info.value.safe_message
    assert base_url not in exc_info.value.safe_message


def test_model_factories_use_independent_slot_configuration() -> None:
    settings = Settings(
        model_a_name="slot-a-model",
        model_a_base_url="https://slot-a.test.invalid/v1",
        model_a_api_key="slot-a-key",
        model_a_timeout=21,
        model_b_name="slot-b-model",
        model_b_base_url="https://slot-b.test.invalid/v1",
        model_b_api_key="slot-b-key",
        model_b_timeout=34,
    )

    model_a = get_model_a(settings)
    model_b = get_model_b(settings)

    assert model_a.model_name == "slot-a-model"
    assert model_b.model_name == "slot-b-model"
    assert model_a._base_url == "https://slot-a.test.invalid/v1"
    assert model_b._base_url == "https://slot-b.test.invalid/v1"


@pytest.fixture
def models_config_client() -> Iterator[tuple[TestClient, uuid.UUID]]:
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
                    email="models-config@example.com",
                    hashed_password="not-used-in-this-test",
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
            model_a_name="configured-a",
            model_a_base_url="https://secret-a.test.invalid/v1",
            model_a_api_key="secret-a-key",
            model_b_name="configured-b",
            model_b_base_url="https://secret-b.test.invalid/v1",
            model_b_api_key="secret-b-key",
        )

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app) as client:
        yield client, user_id

    asyncio.run(engine.dispose())


def test_models_config_requires_authentication_and_returns_names_only(
    models_config_client: tuple[TestClient, uuid.UUID],
) -> None:
    client, user_id = models_config_client

    unauthorized_response = client.get("/models/config")
    assert unauthorized_response.status_code == 401

    response = client.get(
        "/models/config",
        headers={"Authorization": f"Bearer {create_access_token(user_id, TEST_SECRET)}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model_a": {"name": "configured-a"},
        "model_b": {"name": "configured-b"},
    }
    serialized = response.text
    assert "api_key" not in serialized
    assert "base_url" not in serialized
    assert "secret-a-key" not in serialized
    assert "secret-b-key" not in serialized
