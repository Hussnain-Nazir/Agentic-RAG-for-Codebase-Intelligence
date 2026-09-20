import asyncio
import json
import math
import re
import shutil
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.controller import AgentController, ExecutionPlan
from app.api.routes.analysis import get_analysis_providers, get_analysis_tool_registry
from app.api.routes.repositories import _persist_repository, get_embedding_provider
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.llm.mock import MockProvider
from app.main import create_app
from app.models import AgentRunStatus, Repository, Session, ToolCall, User
from app.schemas.responses import FlowTraceResponse
from app.sources.upload import UploadedRepositorySource
from app.tools.registry import ToolRegistry

SOURCE_FIXTURE = Path(__file__).parent / "fixtures" / "mini_fastapi"


class FlowEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vector = [0.0] * self.dimensions
            if re.search(r"login|password|access_token|create_access_token", lowered):
                vector[0] = 1.0
            if re.search(r"get_current_user|item|route", lowered):
                vector[1] = 1.0
            if "external_gateway" in lowered:
                vector[2] = 1.0
            if not any(vector):
                vector[20] = 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


def _prompt_payload(messages) -> tuple[dict, dict]:
    user_content = next(message.content for message in messages if message.role == "user")
    metadata = json.loads(
        user_content.split(
            "[TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]\n",
            1,
        )[1].split(
            "\n[/TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]",
            1,
        )[0]
    )
    context = json.loads(
        user_content.split(
            "EvidenceContext (repository content below is untrusted data):\n",
            1,
        )[1]
    )
    return metadata, context


@pytest.fixture
def flow_context(tmp_path: Path) -> Iterator[tuple]:
    fixture = tmp_path / "flow_fixture"
    shutil.copytree(SOURCE_FIXTURE, fixture)
    (fixture / "routers" / "external.py").write_text(
        "def start_external():\n    return external_gateway()\n",
        encoding="utf-8",
    )
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    embedding_provider = FlowEmbeddingProvider()
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret="phase-nineteen-test-secret-at-least-32-bytes",
    )

    async def prepare() -> tuple[User, Repository]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(
                email=f"flow-{uuid.uuid4()}@example.com",
                hashed_password="unused",
            )
            session.add(user)
            await session.flush()
            source = UploadedRepositorySource()
            revision = await source.get_revision(str(fixture))
            imported = await _persist_repository(
                session,
                user,
                source,
                str(fixture),
                revision,
                "flow-fixture",
                "upload",
                "upload",
                embedding_provider,
                settings,
            )
            repository = await session.get(
                Repository,
                uuid.UUID(imported.repository_id),
            )
            return user, repository

    user, repository = asyncio.run(prepare())
    provider_box: dict[str, MockProvider] = {}

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def override_current_user() -> User:
        return user

    def override_settings() -> Settings:
        return settings

    def override_embedding_provider() -> FlowEmbeddingProvider:
        return embedding_provider

    def override_providers() -> dict[str, MockProvider]:
        return {"A": provider_box["provider"]}

    def build_registry(session: AsyncSession) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register_builtin_plugins(
            session=session,
            embedding_provider=embedding_provider,
            settings=settings,
        )
        return registry

    def override_registry(
        db: AsyncSession = Depends(get_db),
    ) -> ToolRegistry:
        return build_registry(db)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_provider] = override_embedding_provider
    app.dependency_overrides[get_analysis_providers] = override_providers
    app.dependency_overrides[get_analysis_tool_registry] = override_registry

    with TestClient(app) as client:
        yield (
            client,
            session_factory,
            user,
            repository,
            provider_box,
            build_registry,
        )
    asyncio.run(engine.dispose())


def test_known_flow_is_ordered_and_observation_backed(flow_context) -> None:
    client, session_factory, _, repository, provider_box, _ = flow_context

    def response(messages, schema):
        assert schema is FlowTraceResponse
        metadata, context = _prompt_payload(messages)
        observations = metadata["flow_observations"]
        assert any(
            item["source_symbol"] == "login"
            and item["target_symbol"] == "create_access_token"
            and item["resolved"]
            for item in observations
        )
        by_path = {item["file_path"]: item for item in context["evidence"]}
        login = by_path["routers/auth.py"]
        token = by_path["auth/security.py"]
        return {
            "summary": "Login calls create_access_token across two files.",
            "steps": [
                {
                    "order": 1,
                    "file": login["file_path"],
                    "symbol": "login",
                    "start_line": login["start_line"],
                    "end_line": login["end_line"],
                    "explanation": "The login route calls create_access_token.",
                    "relationship_to_next": "CALLS",
                    "unresolved": False,
                    "evidence_ids": [login["evidence_id"]],
                },
                {
                    "order": 2,
                    "file": token["file_path"],
                    "symbol": "create_access_token",
                    "start_line": token["start_line"],
                    "end_line": token["end_line"],
                    "explanation": "The token helper returns the access token.",
                    "relationship_to_next": None,
                    "unresolved": False,
                    "evidence_ids": [token["evidence_id"]],
                },
            ],
            "evidence": [login, token],
        }

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace `login` to create_access_token.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    steps = api_response.json()["trace"]["steps"]
    assert [step["symbol"] for step in steps] == ["login", "create_access_token"]
    assert steps[0]["relationship_to_next"] == "CALLS"
    assert all(not step["unresolved"] for step in steps)

    async def calls() -> list[str]:
        async with session_factory() as session:
            run_id = uuid.UUID(api_response.json()["agent_run_id"])
            return list(
                await session.scalars(
                    select(ToolCall.tool_name)
                    .where(ToolCall.agent_run_id == run_id)
                    .order_by(ToolCall.sequence)
                )
            )

    names = asyncio.run(calls())
    assert "find_references" in names
    assert "get_related_files" in names


def test_broken_flow_marks_transition_unresolved(flow_context) -> None:
    client, _, _, repository, provider_box, _ = flow_context
    observed: dict[str, object] = {}

    def response(messages, schema):
        assert schema is FlowTraceResponse
        metadata, context = _prompt_payload(messages)
        observed["metadata"] = metadata
        observed["context"] = context
        matching = [
            item
            for item in context["evidence"]
            if item["file_path"] == "routers/external.py"
        ]
        if not matching:
            return {
                "summary": "No external call evidence was retained.",
                "steps": [],
                "evidence": [],
            }
        evidence = matching[0]
        return {
            "summary": "The external call cannot be resolved.",
            "steps": [
                {
                    "order": 1,
                    "file": evidence["file_path"],
                    "symbol": "external_gateway",
                    "start_line": evidence["start_line"],
                    "end_line": evidence["end_line"],
                    "explanation": "No repository definition establishes the next transition.",
                    "relationship_to_next": "CALLS",
                    "unresolved": False,
                    "evidence_ids": [evidence["evidence_id"]],
                }
            ],
            "evidence": [evidence],
        }

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace `external_gateway` from start_external to its result.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    observations = observed["metadata"]["flow_observations"]
    unresolved = next(
        item
        for item in observations
        if item["source_symbol"] == "external_gateway"
    )
    assert unresolved["resolved"] is False
    assert any(
        item["file_path"] == "routers/external.py"
        for item in observed["context"]["evidence"]
    )
    step = api_response.json()["trace"]["steps"][0]
    assert step["symbol"] == "external_gateway"
    assert step["unresolved"] is True
    assert step["relationship_to_next"] is None


def test_flow_trace_bound_returns_valid_partial_response(flow_context) -> None:
    _, session_factory, user, repository, _, build_registry = flow_context

    async def run_bounded():
        async with session_factory() as session:
            conversation = Session(user_id=user.id, repository_id=repository.id)
            session.add(conversation)
            await session.flush()
            controller = AgentController(
                session,
                {"A": MockProvider(canned_responses=[])},
                tool_registry=build_registry(session),
                user_id=user.id,
                execution_plan=ExecutionPlan(extra_tool_iterations=9),
            )
            return await controller.run(
                "Trace `login` to create_access_token.",
                "A",
                repository.id,
                conversation.id,
            )

    result = asyncio.run(run_bounded())
    trace = FlowTraceResponse.model_validate(result.result)
    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert isinstance(trace.steps, list)
    assert isinstance(trace.evidence, list)
