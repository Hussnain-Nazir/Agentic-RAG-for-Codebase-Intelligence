import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.controller import MAX_TOOL_ITERATIONS, AgentController
from app.db.base import Base
from app.evidence.models import Evidence
from app.llm.mock import MockProvider
from app.llm.base import LLMResult
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


def test_agent_controller_skeleton_was_replaced_by_bounded_controller() -> None:
    assert AgentController.__module__ == "app.agent.controller"
    assert MAX_TOOL_ITERATIONS == 8


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
                    "apiKey": "must-not-be-stored",
                    "privateKey": "must-not-be-stored",
                    "nested": {
                        "access_token": "must-not-be-stored",
                        "api-key": "must-not-be-stored",
                    },
                },
                ExecutionContext(),
            )
            await hooks.post_tool(run.id, 1, "OK", 2, "one result", None)
            call = await session.scalar(select(ToolCall))

            assert call is not None
            assert call.args_sanitized == {
                "query": "safe",
                "api_key": "[REDACTED]",
                "apiKey": "[REDACTED]",
                "privateKey": "[REDACTED]",
                "nested": {
                    "access_token": "[REDACTED]",
                    "api-key": "[REDACTED]",
                },
            }
            assert call.status == "OK"

    asyncio.run(exercise())


def test_provider_failure_records_elapsed_time_without_raw_error() -> None:
    class FailingProvider:
        model_name = "failure-test"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            await asyncio.sleep(0.02)
            raise RuntimeError("provider included sensitive request details")

    async def exercise() -> None:
        async for session in database_session():
            controller = AgentController(session, FailingProvider(), slot="A")
            with pytest.raises(RuntimeError, match="provider included"):
                await controller.run("Explain behavior")

            execution = await session.scalar(select(ModelExecution))
            assert execution is not None
            assert execution.validation_status == "NOT_VALIDATED"
            assert execution.latency_ms >= 10
            assert execution.input_tokens is None
            assert execution.output_tokens is None
            assert execution.error == "RuntimeError: provider request failed"

    asyncio.run(exercise())


def test_invalid_model_output_retains_elapsed_time_and_token_usage() -> None:
    class InvalidProvider:
        model_name = "validation-test"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            await asyncio.sleep(0.02)
            return LLMResult(
                content='{"wrong_field": "value"}',
                input_tokens=11,
                output_tokens=5,
                latency_ms=3,
                raw_response={},
            )

    async def exercise() -> None:
        async for session in database_session():
            controller = AgentController(session, InvalidProvider(), slot="B")
            with pytest.raises(ValidationError):
                await controller.run("Explain behavior")

            execution = await session.scalar(select(ModelExecution))
            assert execution is not None
            assert execution.validation_status == "INVALID"
            assert execution.latency_ms >= 10
            assert execution.input_tokens == 11
            assert execution.output_tokens == 5
            assert "wrong_field" not in (execution.error or "")

    asyncio.run(exercise())


def test_memory_service_export_uses_phase_thirteen_implementation() -> None:
    assert MemoryService.__module__ == "app.memory.service"


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
