import asyncio
import uuid
from collections.abc import AsyncIterator

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.controller import AgentController
from app.db.base import Base
from app.evidence.models import Evidence
from app.llm.mock import MockProvider
from app.memory.base import MemoryService
from app.models import (
    AgentRun,
    AgentRunStatus,
    ModelExecution,
    Repository,
    RepositoryAccessStatus,
    RepositorySourceType,
    ToolCall,
    User,
)
from app.tools.base import ExecutionContext
from app.tools.registry import ToolRegistry
from app.tracing.hooks import HookManager


async def database_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def test_agent_controller_persists_run_and_model_execution() -> None:
    async def exercise() -> None:
        async for session in database_session():
            provider = MockProvider(canned_responses=[{"answer": "known answer"}])
            controller = AgentController(session, provider, slot="A")

            result = await controller.run("Explain the known behavior")

            run = await session.scalar(select(AgentRun))
            execution = await session.scalar(select(ModelExecution))
            assert result.answer == "known answer"
            assert run is not None
            assert run.status is AgentRunStatus.OK
            assert run.completed_at is not None
            assert execution is not None
            assert execution.agent_run_id == run.id
            assert execution.model_name == "mock"
            assert execution.validation_status == "VALID"
            assert execution.error is None

    asyncio.run(exercise())


class FakeInput(BaseModel):
    value: str


class FakeOutput(BaseModel):
    value: str


class FakeTool:
    name = "fake"
    description = "Test-only registry tool"
    input_schema = FakeInput
    output_schema = FakeOutput
    requires_auth = True

    async def execute(
        self,
        input: BaseModel,
        ctx: ExecutionContext,
    ) -> BaseModel:
        del ctx
        return FakeOutput(value=FakeInput.model_validate(input).value)


def test_tool_registry_registers_gets_and_lists_tools() -> None:
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    assert registry.get("fake") is tool
    assert registry.list() == [tool]


def test_hook_manager_sanitizes_credentials() -> None:
    async def exercise() -> None:
        async for session in database_session():
            run = AgentRun(task_type="REPOSITORY_QA", status=AgentRunStatus.ERROR)
            session.add(run)
            await session.flush()
            hooks = HookManager(session)

            await hooks.pre_tool(
                run.id,
                1,
                "fake",
                {
                    "query": "safe",
                    "api_key": "must-not-be-stored",
                    "nested": {"access_token": "must-not-be-stored"},
                },
                ExecutionContext(),
            )
            await hooks.post_tool(run.id, 1, "OK", 2, "one result", None)
            call = await session.scalar(select(ToolCall))

            assert call is not None
            assert call.args_sanitized == {
                "query": "safe",
                "api_key": "[REDACTED]",
                "nested": {"access_token": "[REDACTED]"},
            }
            assert call.status == "OK"

    asyncio.run(exercise())


def test_minimal_memory_service_can_save_retrieve_and_invalidate() -> None:
    async def exercise() -> None:
        async for session in database_session():
            user = User(email="memory@example.com", hashed_password="unused")
            repository = Repository(
                owner=user,
                source_type=RepositorySourceType.UPLOAD,
                name="memory-fixture",
                default_branch="main",
                selected_branch="main",
                access_status=RepositoryAccessStatus.ACTIVE,
            )
            session.add(repository)
            await session.flush()
            memory = MemoryService(session)

            await memory.save(
                repository.id,
                repository_index_version=1,
                scope="repository",
                topic="authentication",
                content="JWT authentication is used",
            )
            assert len(await memory.retrieve(repository.id, "authentication")) == 1
            assert await memory.invalidate_stale(repository.id, 2) == 1
            assert await memory.retrieve(repository.id, "authentication") == []

    asyncio.run(exercise())


def test_evidence_model_accepts_all_specified_fields() -> None:
    evidence = Evidence(
        evidence_id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        repository_index_id=uuid.uuid4(),
        source_type="CODE",
        file_path="backend/app/main.py",
        symbol="create_app",
        start_line=1,
        end_line=10,
        content_excerpt="def create_app(): ...",
        relationship_metadata={"kind": "caller"},
        retrieval_metadata={"score": 0.83, "signal": "semantic+symbol"},
        external_source_metadata=None,
    )

    assert evidence.source_type == "CODE"
    assert evidence.file_path == "backend/app/main.py"
