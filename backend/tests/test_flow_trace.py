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
from app.evidence.context_builder import ContextBuilder
from app.evidence.models import EvidenceQuality
from app.llm.mock import MockProvider
from app.main import create_app
from app.models import (
    AgentRunStatus,
    ModelExecution,
    Repository,
    Session,
    ToolCall,
    User,
)
from app.schemas.responses import FlowTraceResponse
from app.sources.upload import UploadedRepositorySource
from app.tools.base import ExecutionContext
from app.tools.registry import ToolRegistry
from app.tools.schemas import RepositoryQueryInput

SOURCE_FIXTURE = Path(__file__).parent / "fixtures" / "mini_fastapi"
GENERAL_FIXTURE = Path(__file__).parent / "fixtures" / "flow_general"


class FlowEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vector = [0.0] * self.dimensions
            if re.search(r"login|password|access_token|create_access_token", lowered):
                vector[0] = 1.0
            if re.search(r"jwt|secret", lowered):
                vector[0] = 1.0
            if re.search(r"get_current_user|item|route", lowered):
                vector[1] = 1.0
            if "external_gateway" in lowered:
                vector[2] = 1.0
            if re.search(r"session|database|create_session", lowered):
                vector[3] = 1.0
            if re.search(
                r"stripe|kubernetes|redis|emails sent|docker deployment",
                lowered,
            ):
                vector[10] = 1.0
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


def _response_from_graph(messages, schema, first_relationship: str | None = None):
    assert schema is FlowTraceResponse
    metadata, context = _prompt_payload(messages)
    graph = metadata["flow_graph"]
    nodes = {item["symbol"]: item for item in graph["nodes"]}
    edges = {
        (item["source_symbol"], item["target_symbol"]): item
        for item in graph["edges"]
    }
    evidence_by_id = {item["evidence_id"]: item for item in context["evidence"]}
    steps = []
    cited_ids: list[str] = []
    for index, symbol in enumerate(graph["path"]):
        node = nodes[symbol]
        next_symbol = (
            graph["path"][index + 1]
            if index + 1 < len(graph["path"])
            else None
        )
        edge = edges.get((symbol, next_symbol)) if next_symbol else None
        relationship = edge["kind"] if edge else None
        if index == 0 and first_relationship is not None:
            relationship = first_relationship
        cited_ids.extend(node["evidence_ids"])
        steps.append(
            {
                "order": index + 1,
                "file": node["file"],
                "symbol": symbol,
                "start_line": node["start_line"],
                "end_line": node["end_line"],
                "explanation": f"Observed {symbol}.",
                "relationship_to_next": relationship,
                "unresolved": node["unresolved"],
                "evidence_ids": node["evidence_ids"],
            }
        )
    return {
        "summary": "Model-rendered flow trace.",
        "steps": steps,
        "evidence": [
            evidence_by_id[item]
            for item in dict.fromkeys(cited_ids)
            if item in evidence_by_id
        ],
    }


@pytest.fixture
def flow_context(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[tuple]:
    fixture = tmp_path / "flow_fixture"
    source_fixture = getattr(request, "param", SOURCE_FIXTURE)
    shutil.copytree(source_fixture, fixture)
    if source_fixture == SOURCE_FIXTURE:
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
    provider_calls = {"count": 0}
    observed: dict[str, object] = {}

    def response(messages, schema):
        assert schema is FlowTraceResponse
        provider_calls["count"] += 1
        metadata, context = _prompt_payload(messages)
        graph = metadata["flow_graph"]
        observed.update(graph)
        nodes = {item["symbol"]: item for item in graph["nodes"]}
        edges = {
            (item["source_symbol"], item["target_symbol"]): item
            for item in graph["edges"]
        }
        evidence_by_id = {
            item["evidence_id"]: item for item in context["evidence"]
        }
        steps = []
        cited_ids: list[str] = []
        for index, symbol in enumerate(graph["path"]):
            node = nodes[symbol]
            next_symbol = (
                graph["path"][index + 1]
                if index + 1 < len(graph["path"])
                else None
            )
            edge = edges.get((symbol, next_symbol)) if next_symbol else None
            evidence_ids = node["evidence_ids"]
            cited_ids.extend(evidence_ids)
            steps.append(
                {
                    "order": index + 1,
                    "file": node["file"],
                    "symbol": symbol,
                    "start_line": node["start_line"],
                    "end_line": node["end_line"],
                    "explanation": f"Observed {symbol}.",
                    "relationship_to_next": edge["kind"] if edge else None,
                    "unresolved": node["unresolved"],
                    "evidence_ids": evidence_ids,
                }
            )
        return {
            "summary": "Login verifies the password and creates a token.",
            "steps": steps,
            "evidence": [
                evidence_by_id[item]
                for item in dict.fromkeys(cited_ids)
                if item in evidence_by_id
            ],
        }

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace what happens when a user logs in.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    assert observed["path"] == [
        "login",
        "create_access_token",
        "verify_password",
    ]
    assert all(edge["kind"] != "IMPORTS" for edge in observed["edges"])
    assert all(edge["kind"] != "SEQUENCE" for edge in observed["edges"])
    assert {
        (edge["source_symbol"], edge["target_symbol"])
        for edge in observed["edges"]
    } == {
        ("login", "verify_password"),
        ("login", "create_access_token"),
    }
    steps = api_response.json()["trace"]["steps"]
    assert [step["symbol"] for step in steps] == [
        "login",
        "create_access_token",
        "verify_password",
    ]
    assert steps[0]["relationship_to_next"] == "CALLS"
    assert steps[1]["relationship_to_next"] is None
    assert steps[-1]["relationship_to_next"] is None
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
    assert "get_related_files" in names
    assert len(names) <= 8
    assert provider_calls["count"] == 1


def test_create_item_flow_is_forward_only_and_reaches_model(flow_context) -> None:
    client, session_factory, _, repository, provider_box, _ = flow_context
    calls = {"count": 0}
    observed: dict[str, object] = {}

    def response(messages, schema):
        calls["count"] += 1
        metadata, _ = _prompt_payload(messages)
        observed.update(metadata["flow_graph"])
        return _response_from_graph(messages, schema)

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace what happens when an authenticated user creates an item.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    assert observed["path"] == ["create_item", "get_current_user"]
    assert all(edge["kind"] != "IMPORTS" for edge in observed["edges"])
    steps = api_response.json()["trace"]["steps"]
    assert [item["symbol"] for item in steps] == [
        "create_item",
        "get_current_user",
    ]
    assert all(item["symbol"] != "list_items" for item in steps)
    assert steps[0]["relationship_to_next"] == "CALLS"
    assert steps[-1]["relationship_to_next"] is None
    assert calls["count"] == 1

    async def persisted():
        async with session_factory() as session:
            run_id = uuid.UUID(api_response.json()["agent_run_id"])
            tools = list(
                await session.scalars(
                    select(ToolCall)
                    .where(ToolCall.agent_run_id == run_id)
                    .order_by(ToolCall.sequence)
                )
            )
            models = list(
                await session.scalars(
                    select(ModelExecution).where(ModelExecution.agent_run_id == run_id)
                )
            )
            return tools, models

    tools, models = asyncio.run(persisted())
    assert len(tools) <= 8
    assert len(models) == 1


def test_unbacked_model_transition_is_rejected_by_deterministic_fallback(
    flow_context,
) -> None:
    client, _, _, repository, provider_box, _ = flow_context

    def fabricated_response(messages, schema):
        response = _response_from_graph(messages, schema)
        first = dict(response["steps"][0])
        fabricated = {
            **first,
            "order": 2,
            "symbol": "fabricated_transition",
            "relationship_to_next": "CALLS",
        }
        response["steps"] = [first, fabricated, response["steps"][1]]
        response["steps"][2]["order"] = 3
        return response

    provider_box["provider"] = MockProvider(callback=fabricated_response)

    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace what happens when an authenticated user creates an item.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    steps = api_response.json()["trace"]["steps"]
    assert [item["symbol"] for item in steps] == [
        "create_item",
        "get_current_user",
    ]
    assert steps[0]["relationship_to_next"] == "CALLS"
    assert steps[-1]["relationship_to_next"] is None


def test_resolved_step_without_citation_falls_back_to_observed_evidence(
    flow_context,
) -> None:
    client, _, _, repository, provider_box, _ = flow_context

    def uncited_response(messages, schema):
        response = _response_from_graph(messages, schema)
        response["steps"][0]["evidence_ids"] = []
        response["steps"][0]["relationship_to_next"] = "CALLS"
        return response

    provider_box["provider"] = MockProvider(callback=uncited_response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace what happens when an authenticated user creates an item.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    steps = api_response.json()["trace"]["steps"]
    assert [step["symbol"] for step in steps] == ["create_item", "get_current_user"]
    assert steps[0]["relationship_to_next"] == "CALLS"
    assert steps[0]["evidence_ids"]
    assert not steps[0]["unresolved"]


def test_broken_flow_marks_transition_unresolved(flow_context) -> None:
    client, _, _, repository, provider_box, _ = flow_context
    observed: dict[str, object] = {}

    def response(messages, schema):
        assert schema is FlowTraceResponse
        metadata, context = _prompt_payload(messages)
        observed["metadata"] = metadata
        observed["context"] = context
        graph = metadata["flow_graph"]
        assert graph["path"] == ["start_external", "external_gateway"]
        nodes = {item["symbol"]: item for item in graph["nodes"]}
        evidence_by_id = {
            item["evidence_id"]: item for item in context["evidence"]
        }
        start = nodes["start_external"]
        external = nodes["external_gateway"]
        evidence_ids = list(
            dict.fromkeys([*start["evidence_ids"], *external["evidence_ids"]])
        )
        return {
            "summary": "The external call cannot be resolved.",
            "steps": [
                {
                    "order": 1,
                    "file": start["file"],
                    "symbol": "start_external",
                    "start_line": start["start_line"],
                    "end_line": start["end_line"],
                    "explanation": "start_external calls external_gateway.",
                    "relationship_to_next": "CALLS",
                    "unresolved": False,
                    "evidence_ids": start["evidence_ids"],
                },
                {
                    "order": 2,
                    "file": external["file"],
                    "symbol": "external_gateway",
                    "start_line": external["start_line"],
                    "end_line": external["end_line"],
                    "explanation": "No repository definition establishes the next transition.",
                    "relationship_to_next": None,
                    "unresolved": True,
                    "evidence_ids": external["evidence_ids"],
                }
            ],
            "evidence": [
                evidence_by_id[item]
                for item in evidence_ids
                if item in evidence_by_id
            ],
        }

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace start_external to `external_gateway`.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    graph = observed["metadata"]["flow_graph"]
    unresolved = next(
        item for item in graph["nodes"] if item["symbol"] == "external_gateway"
    )
    assert unresolved["unresolved"] is True
    assert any(
        item["file_path"] == "routers/external.py"
        for item in observed["context"]["evidence"]
    )
    steps = api_response.json()["trace"]["steps"]
    assert steps[0]["symbol"] == "start_external"
    assert steps[0]["relationship_to_next"] == "CALLS"
    step = steps[1]
    assert step["symbol"] == "external_gateway"
    assert step["unresolved"] is True
    assert step["relationship_to_next"] is None


@pytest.mark.parametrize("flow_context", [GENERAL_FIXTURE], indirect=True)
def test_unrelated_repository_traces_branches_and_external_call(flow_context) -> None:
    client, _, _, repository, provider_box, _ = flow_context
    observed: dict[str, object] = {}

    def response(messages, schema):
        metadata, _ = _prompt_payload(messages)
        observed.update(metadata["flow_graph"])
        return _response_from_graph(messages, schema)

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace register_user through its external library call.",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    assert observed["path"] == ["register_user", "hash_pw", "digest", "store_user"]
    edges = {
        (edge["source_symbol"], edge["target_symbol"], edge["kind"])
        for edge in observed["edges"]
    }
    assert ("register_user", "hash_pw", "CALLS") in edges
    assert ("register_user", "store_user", "CALLS") in edges
    assert ("hash_pw", "digest", "CALLS") in edges
    assert not any(edge[2] == "SEQUENCE" for edge in edges)
    steps = api_response.json()["trace"]["steps"]
    assert [step["symbol"] for step in steps] == observed["path"]
    assert [step["relationship_to_next"] for step in steps] == [
        "CALLS", "CALLS", None, None
    ]
    assert steps[2]["unresolved"] is True
    assert "digest" in next(item["content_excerpt"] for item in api_response.json()["trace"]["evidence"] if item["file_path"] == "workers.py")


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


def test_absent_flow_returns_422_without_model_execution(flow_context) -> None:
    client, session_factory, _, repository, provider_box, _ = flow_context

    def unexpected_model_call(messages, schema):
        del messages, schema
        pytest.fail("The absent-topic flow must not invoke a model")

    provider_box["provider"] = MockProvider(callback=unexpected_model_call)
    response = client.post(
        f"/repositories/{repository.id}/flow-trace",
        json={
            "question": "Trace how the Stripe payment webhook is processed",
            "model_slot": "A",
        },
    )

    assert response.status_code == 422
    assert "Insufficient repository evidence" in response.json()["detail"]["message"]

    async def model_executions() -> list[ModelExecution]:
        async with session_factory() as session:
            run_id = uuid.UUID(response.json()["detail"]["agent_run_id"])
            return list(
                await session.scalars(
                    select(ModelExecution).where(ModelExecution.agent_run_id == run_id)
                )
            )

    assert asyncio.run(model_executions()) == []


@pytest.mark.parametrize(
    "question",
    [
        "How does login work and where is the access token created?",
        "Where is the JWT secret loaded, and where is it used?",
        "What does get_current_user do and which routes depend on it?",
        "How are users authenticated when they create an item?",
        "How is session handling done for database access?",
        "Trace what happens when a user logs in",
        "Trace what happens when an authenticated user creates an item",
        "Trace create_access_token to sha256",
    ],
)
def test_real_search_path_keeps_legitimate_questions(question, flow_context) -> None:
    _, session_factory, user, repository, _, build_registry = flow_context

    async def classify() -> EvidenceQuality:
        async with session_factory() as session:
            result = await build_registry(session).get("search_codebase").execute(
                RepositoryQueryInput(
                    repository_id=repository.id,
                    query=question,
                    top_k=12,
                ),
                ExecutionContext(repository_id=repository.id, user_id=user.id),
            )
            return ContextBuilder().build_from_evidence(
                question,
                "REPOSITORY_QA",
                [],
                list(result.root),
            ).quality

    assert asyncio.run(classify()) is not EvidenceQuality.NONE


@pytest.mark.parametrize(
    "question",
    [
        "How does the Stripe payment webhook work?",
        "Trace how the Stripe payment webhook is processed",
        "How is Kubernetes autoscaling configured?",
        "How is Redis cache configuration implemented?",
        "How are emails sent to users?",
        "Explain the Docker deployment",
    ],
)
def test_real_search_path_rejects_absent_questions(question, flow_context) -> None:
    _, session_factory, user, repository, _, build_registry = flow_context

    async def classify() -> EvidenceQuality:
        async with session_factory() as session:
            result = await build_registry(session).get("search_codebase").execute(
                RepositoryQueryInput(
                    repository_id=repository.id,
                    query=question,
                    top_k=12,
                ),
                ExecutionContext(repository_id=repository.id, user_id=user.id),
            )
            return ContextBuilder().build_from_evidence(
                question,
                "FLOW_TRACE",
                [],
                list(result.root),
            ).quality

    assert asyncio.run(classify()) is EvidenceQuality.NONE
