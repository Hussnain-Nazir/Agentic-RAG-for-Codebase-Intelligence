import asyncio
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.classification import TaskType, classify_task
from app.agent.controller import AgentController, ExecutionPlan
from app.api.routes.repositories import _persist_repository
from app.config import Settings
from app.db.base import Base
from app.evidence.models import Evidence
from app.llm.base import LLMResult
from app.models import (
    AgentRun,
    AgentRunStatus,
    CodeChunk,
    ModelExecution,
    Repository,
    RepositoryIndex,
    Session,
    ToolCall,
    User,
)
from app.plugins.web_search.provider import WebResult
from app.schemas.responses import (
    ArchitectureResponse,
    ChangeImpactResponse,
    FlowTraceResponse,
    RepositoryAnswer,
)
from app.sources.upload import UploadedRepositorySource
from app.tools.registry import ToolRegistry
from app.tools.errors import UnauthorizedRepositoryAccessError
from app.tools.schemas import EvidenceList, RelatedFilesInput, RepositoryQueryInput

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_fastapi"


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]


class FakeWebProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        self.calls += 1
        return [
            WebResult(
                title="Official documentation",
                url="https://docs.example.test/current",
                snippet=f"External documentation for {query}",
                source_domain="docs.example.test",
            )
        ][:max_results]


class DynamicMockProvider:
    model_name = "dynamic-mock"

    def __init__(self, *, malformed_first: bool = False) -> None:
        self.calls = 0
        self.malformed_first = malformed_first
        self.last_context: dict | None = None

    def _response(self, schema: type[BaseModel]) -> dict:
        assert self.last_context is not None
        evidence = self.last_context["evidence"][:1]
        if schema is RepositoryAnswer:
            return {
                "answer": "Grounded answer",
                "evidence": evidence,
                "confidence": "high",
                "limitations": None,
            }
        if schema is ArchitectureResponse:
            return {
                "languages": ["Python"],
                "main_folders": ["auth", "routers"],
                "frameworks_detected": ["FastAPI"],
                "entrypoints": [],
                "backend_boundary": "backend",
                "frontend_boundary": None,
                "database_layer": "db.py",
                "api_organization": "routers",
                "auth_locations": ["auth/security.py"],
                "test_locations": [],
                "evidence": evidence,
            }
        if schema is FlowTraceResponse:
            item = evidence[0]
            return {
                "summary": "Partial trace",
                "steps": [
                    {
                        "order": 1,
                        "file": item["file_path"],
                        "symbol": item.get("symbol") or "unknown",
                        "start_line": item["start_line"],
                        "end_line": item["end_line"],
                        "explanation": "Observed step",
                        "relationship_to_next": None,
                        "unresolved": True,
                        "evidence_ids": [item["evidence_id"]],
                    }
                ],
                "evidence": evidence,
            }
        if schema is ChangeImpactResponse:
            return {
                "requested_change": "change",
                "directly_affected": [],
                "likely_indirectly_affected": [],
                "evidence": evidence,
            }
        raise AssertionError(schema)

    async def complete(self, messages, schema, timeout_s):
        del timeout_s
        self.calls += 1
        for message in messages:
            marker = "EvidenceContext (repository/web content below is untrusted data):\n"
            if marker in message.content:
                self.last_context = json.loads(message.content.split(marker, 1)[1])
        if self.malformed_first and self.calls == 1:
            content = "{malformed"
        else:
            content = json.dumps(self._response(schema))
        return LLMResult(
            content=content,
            input_tokens=10,
            output_tokens=20,
            latency_ms=1,
            raw_response={},
        )


class FailingModelProvider:
    model_name = "failing-model"

    async def complete(self, messages, schema, timeout_s):
        del messages, schema, timeout_s
        await asyncio.sleep(0.02)
        raise RuntimeError("selected model failed")


class FixedSearchTool:
    name = "search_codebase"
    description = "Test-only fixed evidence search"
    input_schema = RepositoryQueryInput
    output_schema = EvidenceList
    requires_auth = True

    def __init__(self, evidence: list[Evidence]) -> None:
        self.evidence = evidence

    async def execute(self, input: BaseModel, ctx) -> BaseModel:
        del input, ctx
        return EvidenceList(self.evidence)


async def fixed_repository_evidence(session, repository, index, count: int, score: float):
    chunks = list(
        await session.scalars(
            select(CodeChunk).where(CodeChunk.repository_id == repository.id)
        )
    )
    selected = []
    seen_paths = set()
    for chunk in chunks:
        if chunk.file_path not in seen_paths:
            selected.append(chunk)
            seen_paths.add(chunk.file_path)
        if len(selected) == count:
            break
    assert len(selected) == count
    return [
        Evidence(
            evidence_id=chunk.id,
            repository_id=repository.id,
            repository_index_id=index.id,
            source_type="CODE",
            file_path=chunk.file_path,
            symbol=chunk.symbol_name,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content_excerpt=chunk.content,
            relationship_metadata={},
            retrieval_metadata={"score": score, "signal": "semantic"},
            external_source_metadata=None,
        )
        for chunk in selected
    ]


@pytest_asyncio.fixture
async def orchestration_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(email=f"agent-{uuid.uuid4()}@example.com", hashed_password="unused")
        session.add(user)
        await session.flush()
        source = UploadedRepositorySource()
        revision = await source.get_revision(str(FIXTURE_ROOT))
        imported = await _persist_repository(
            session,
            user,
            source,
            str(FIXTURE_ROOT),
            revision,
            "agent-fixture",
            "upload",
            "upload",
            FakeEmbeddingProvider(),
            Settings(database_url="sqlite+aiosqlite://"),
        )
        repository = await session.get(Repository, uuid.UUID(imported.repository_id))
        index = await session.get(RepositoryIndex, uuid.UUID(imported.index_id))
        conversation = Session(user_id=user.id, repository_id=repository.id)
        session.add(conversation)
        await session.flush()

        def registry(web_provider=None):
            value = ToolRegistry()
            value.register_builtin_plugins(
                session=session,
                embedding_provider=FakeEmbeddingProvider(),
                web_search_provider=web_provider or FakeWebProvider(),
                settings=Settings(database_url="sqlite+aiosqlite://"),
            )
            return value

        yield session, user, repository, index, conversation, registry
    await engine.dispose()


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("Open routers/auth.py", TaskType.DIRECT_FILE_OP),
        ("create_access_token", TaskType.SYMBOL_LOOKUP),
        ("Find UserService", TaskType.SYMBOL_LOOKUP),
        ("Where is create_access_token referenced?", TaskType.REFERENCE_LOOKUP),
        ("How does authentication work?", TaskType.REPOSITORY_QA),
        ("Explain the architecture", TaskType.ARCHITECTURE_EXPLANATION),
        ("Trace login from form to token", TaskType.FLOW_TRACE),
        ("What would be affected if User changed?", TaskType.CHANGE_IMPACT),
        ("Compare with current official docs", TaskType.EXTERNAL_DOC_QUERY),
        ("What does UserService do?", TaskType.REPOSITORY_QA),
    ],
)
def test_task_classification(task: str, expected: TaskType) -> None:
    assert classify_task(task) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task",
    [
        "Open routers/auth.py",
        "create_access_token",
        "Where is create_access_token referenced?",
    ],
)
async def test_direct_tasks_make_zero_model_calls(orchestration_context, task) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    provider = DynamicMockProvider()
    controller = AgentController(
        session,
        {"A": provider},
        tool_registry=registry_factory(),
        user_id=user.id,
    )

    result = await controller.run(task, "A", repository.id, conversation.id)

    assert result.status is AgentRunStatus.OK
    assert provider.calls == 0
    executions = list(await session.scalars(select(ModelExecution)))
    assert executions == []


@pytest.mark.asyncio
async def test_controller_requires_authenticated_user_identity(orchestration_context) -> None:
    session, _, repository, _, conversation, registry_factory = orchestration_context
    controller = AgentController(
        session, {"A": DynamicMockProvider()}, tool_registry=registry_factory()
    )

    with pytest.raises(UnauthorizedRepositoryAccessError, match="Authenticated user"):
        await controller.run(
            "How does authentication work?", "A", repository.id, conversation.id
        )
    assert list(await session.scalars(select(AgentRun))) == []


@pytest.mark.asyncio
async def test_repository_qa_calls_one_model_and_persists_trace(
    orchestration_context,
) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    model_a = DynamicMockProvider()
    model_b = DynamicMockProvider()
    controller = AgentController(
        session,
        {"A": model_a, "B": model_b},
        tool_registry=registry_factory(),
        user_id=user.id,
    )

    result = await controller.run(
        "How does authentication work?",
        "A",
        repository.id,
        conversation.id,
    )

    assert result.status is AgentRunStatus.OK
    assert model_a.calls == 1
    assert model_b.calls == 0
    run = await session.get(AgentRun, result.agent_run_id)
    calls = list(
        await session.scalars(
            select(ToolCall)
            .where(ToolCall.agent_run_id == result.agent_run_id)
            .order_by(ToolCall.sequence)
        )
    )
    executions = list(
        await session.scalars(
            select(ModelExecution).where(
                ModelExecution.agent_run_id == result.agent_run_id
            )
        )
    )
    assert run.status is AgentRunStatus.OK
    assert [item.tool_name for item in calls] == ["retrieve_memory", "search_codebase"]
    assert all(item.status == "OK" for item in calls)
    assert len(executions) == 1
    assert executions[0].validation_status == "VALID"
    assert result.evidence_context.evidence


@pytest.mark.asyncio
async def test_external_query_uses_web_but_ordinary_qa_does_not(
    orchestration_context,
) -> None:
    session, user, repository, index, conversation, registry_factory = orchestration_context
    web = FakeWebProvider()
    provider = DynamicMockProvider()
    strong_registry = registry_factory(web)
    strong_registry._tools["search_codebase"] = FixedSearchTool(
        await fixed_repository_evidence(session, repository, index, 3, 0.9)
    )
    controller = AgentController(
        session,
        {"A": provider},
        tool_registry=strong_registry,
        user_id=user.id,
    )

    ordinary = await controller.run(
        "How does authentication work?", "A", repository.id, conversation.id
    )
    strong_external = await controller.run(
        "Compare authentication with official docs",
        "A",
        repository.id,
        conversation.id,
    )
    weak_registry = registry_factory(web)
    weak_registry._tools["search_codebase"] = FixedSearchTool(
        await fixed_repository_evidence(session, repository, index, 1, 0.2)
    )
    weak_controller = AgentController(
        session, {"A": provider}, tool_registry=weak_registry, user_id=user.id
    )
    weak_external = await weak_controller.run(
        "Compare authentication with official docs", "A", repository.id, conversation.id
    )

    ordinary_names = list(
        await session.scalars(
            select(ToolCall.tool_name).where(
                ToolCall.agent_run_id == ordinary.agent_run_id
            )
        )
    )
    strong_names = list(
        await session.scalars(
            select(ToolCall.tool_name).where(
                ToolCall.agent_run_id == strong_external.agent_run_id
            )
        )
    )
    weak_names = list(
        await session.scalars(
            select(ToolCall.tool_name).where(
                ToolCall.agent_run_id == weak_external.agent_run_id
            )
        )
    )
    assert "search_web" not in ordinary_names
    assert "search_web" not in strong_names
    assert "search_web" in weak_names
    assert web.calls == 1


@pytest.mark.asyncio
async def test_web_failure_is_traced_and_reported_as_a_limitation(
    orchestration_context,
) -> None:
    class FailingWebProvider:
        async def search(self, query: str, max_results: int = 5):
            del query, max_results
            raise RuntimeError("provider failure details")

    session, user, repository, index, conversation, registry_factory = orchestration_context
    registry = registry_factory(FailingWebProvider())
    registry._tools["search_codebase"] = FixedSearchTool(
        await fixed_repository_evidence(session, repository, index, 1, 0.2)
    )
    controller = AgentController(
        session, {"A": DynamicMockProvider()}, tool_registry=registry, user_id=user.id
    )

    result = await controller.run(
        "Compare authentication with official docs", "A", repository.id, conversation.id
    )
    web_call = await session.scalar(
        select(ToolCall).where(
            ToolCall.agent_run_id == result.agent_run_id,
            ToolCall.tool_name == "search_web",
        )
    )

    assert result.status is AgentRunStatus.OK
    assert web_call is not None and web_call.status == "ERROR"
    assert web_call.error == "Web search failed"
    assert "Web search failed" in result.result["limitations"]
    assert "provider failure details" not in result.result["limitations"]


@pytest.mark.asyncio
async def test_tool_iteration_bound_stops_at_eight(orchestration_context) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    provider = DynamicMockProvider()
    controller = AgentController(
        session,
        {"A": provider},
        tool_registry=registry_factory(),
        user_id=user.id,
        execution_plan=ExecutionPlan(extra_tool_iterations=9),
    )

    result = await controller.run(
        "How does authentication work?", "A", repository.id, conversation.id
    )

    calls = list(
        await session.scalars(
            select(ToolCall).where(ToolCall.agent_run_id == result.agent_run_id)
        )
    )
    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert len(calls) == 8
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_structural_round_bound_stops_after_three(orchestration_context) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    controller = AgentController(
        session,
        {"A": DynamicMockProvider()},
        tool_registry=registry_factory(),
        user_id=user.id,
        execution_plan=ExecutionPlan(structural_expansion_rounds=4),
    )

    result = await controller.run(
        "Trace `create_access_token` from login to token",
        "A",
        repository.id,
        conversation.id,
    )

    names = list(
        await session.scalars(
            select(ToolCall.tool_name).where(
                ToolCall.agent_run_id == result.agent_run_id
            )
        )
    )
    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert names.count("get_related_files") == 3


class TooManyRelatedTool:
    name = "get_related_files"
    description = "Bound forcing tool"
    input_schema = RelatedFilesInput
    output_schema = EvidenceList
    requires_auth = True

    def __init__(self, repository_id, index_id):
        self.repository_id = repository_id
        self.index_id = index_id

    async def execute(self, input: BaseModel, ctx):
        del input, ctx
        return EvidenceList(
            [
                Evidence(
                    evidence_id=uuid.uuid4(),
                    repository_id=self.repository_id,
                    repository_index_id=self.index_id,
                    source_type="CODE",
                    file_path=f"related_{number}.py",
                    symbol=f"related_{number}",
                    start_line=1,
                    end_line=2,
                    content_excerpt="related",
                    relationship_metadata={},
                    retrieval_metadata={
                        "score": 0.5,
                        "signal": "structural",
                        "file_line_count": 2,
                    },
                    external_source_metadata=None,
                )
                for number in range(16)
            ]
        )


@pytest.mark.asyncio
async def test_structural_chunk_bound_stops_at_fifteen(orchestration_context) -> None:
    session, user, repository, index, conversation, registry_factory = orchestration_context
    registry = registry_factory()
    registry._tools["get_related_files"] = TooManyRelatedTool(repository.id, index.id)
    controller = AgentController(
        session,
        {"A": DynamicMockProvider()},
        tool_registry=registry,
        user_id=user.id,
        execution_plan=ExecutionPlan(structural_expansion_rounds=1),
    )

    result = await controller.run(
        "Trace `create_access_token` from login to token",
        "A",
        repository.id,
        conversation.id,
    )

    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert len(result.evidence_context.evidence) <= 12


@pytest.mark.asyncio
async def test_web_search_bound_stops_after_two(orchestration_context) -> None:
    session, user, repository, index, conversation, registry_factory = orchestration_context
    registry = registry_factory()
    registry._tools["search_codebase"] = FixedSearchTool(
        await fixed_repository_evidence(session, repository, index, 1, 0.2)
    )
    controller = AgentController(
        session,
        {"A": DynamicMockProvider()},
        tool_registry=registry,
        user_id=user.id,
        execution_plan=ExecutionPlan(web_searches=3),
    )

    result = await controller.run(
        "Compare authentication with official docs",
        "A",
        repository.id,
        conversation.id,
    )

    names = list(
        await session.scalars(
            select(ToolCall.tool_name).where(
                ToolCall.agent_run_id == result.agent_run_id
            )
        )
    )
    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert names.count("search_web") == 2


@pytest.mark.asyncio
async def test_model_call_bound_never_invokes_second_model(orchestration_context) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    model_a = DynamicMockProvider()
    model_b = DynamicMockProvider()
    controller = AgentController(
        session,
        {"A": model_a, "B": model_b},
        tool_registry=registry_factory(),
        user_id=user.id,
        execution_plan=ExecutionPlan(model_calls=2),
    )

    result = await controller.run(
        "How does authentication work?", "A", repository.id, conversation.id
    )

    assert result.status is AgentRunStatus.BOUNDS_EXCEEDED
    assert model_a.calls == 1
    assert model_b.calls == 0


@pytest.mark.asyncio
async def test_malformed_output_gets_exactly_one_repair(orchestration_context) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    provider = DynamicMockProvider(malformed_first=True)
    controller = AgentController(
        session,
        {"A": provider},
        tool_registry=registry_factory(),
        user_id=user.id,
    )

    result = await controller.run(
        "How does authentication work?", "A", repository.id, conversation.id
    )

    executions = list(
        await session.scalars(
            select(ModelExecution)
            .where(ModelExecution.agent_run_id == result.agent_run_id)
            .order_by(ModelExecution.id)
        )
    )
    assert result.status is AgentRunStatus.OK
    assert provider.calls == 2
    assert {item.validation_status for item in executions} == {
        "INVALID",
        "REPAIRED_VALID",
    }
    assert all(item.latency_ms == 1 for item in executions)
    assert all((item.input_tokens, item.output_tokens) == (10, 20) for item in executions)


@pytest.mark.asyncio
async def test_failed_repair_keeps_returned_model_metrics(orchestration_context) -> None:
    class AlwaysMalformedProvider:
        model_name = "malformed-test"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            return LLMResult(
                content="{invalid",
                input_tokens=3,
                output_tokens=4,
                latency_ms=7,
                raw_response={},
            )

    session, user, repository, _, conversation, registry_factory = orchestration_context
    controller = AgentController(
        session,
        {"A": AlwaysMalformedProvider()},
        tool_registry=registry_factory(),
        user_id=user.id,
    )
    result = await controller.run(
        "How does authentication work?", "A", repository.id, conversation.id
    )
    executions = list(
        await session.scalars(
            select(ModelExecution).where(ModelExecution.agent_run_id == result.agent_run_id)
        )
    )

    assert result.status is AgentRunStatus.INVALID_OUTPUT
    assert len(executions) == 2
    assert all(item.validation_status == "INVALID" for item in executions)
    assert all(item.latency_ms == 7 for item in executions)
    assert all((item.input_tokens, item.output_tokens) == (3, 4) for item in executions)


@pytest.mark.asyncio
async def test_selected_model_failure_is_traced_without_fallback(
    orchestration_context,
) -> None:
    session, user, repository, _, conversation, registry_factory = orchestration_context
    unused_model_b = DynamicMockProvider()
    controller = AgentController(
        session,
        {"A": FailingModelProvider(), "B": unused_model_b},
        tool_registry=registry_factory(),
        user_id=user.id,
    )

    with pytest.raises(RuntimeError, match="selected model failed"):
        await controller.run(
            "How does authentication work?", "A", repository.id, conversation.id
        )

    run = await session.scalar(select(AgentRun).order_by(AgentRun.started_at.desc()))
    execution = await session.scalar(
        select(ModelExecution).where(ModelExecution.agent_run_id == run.id)
    )
    assert run.status is AgentRunStatus.ERROR
    assert execution.model_name == "failing-model"
    assert execution.validation_status == "NOT_VALIDATED"
    assert execution.latency_ms >= 10
    assert execution.error == "RuntimeError: selected model request failed"
    assert unused_model_b.calls == 0
