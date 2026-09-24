import asyncio
import json

from sqlalchemy import select

from app.llm.mock import MockProvider
from app.models import AgentRun, ModelExecution, ToolCall
from app.schemas.responses import ArchitectureResponse
from app.tools.base import ExecutionContext
from app.tools.repository_tools import InspectRepositoryTool
from app.tools.schemas import InspectRepositoryInput
from test_codebase_qa import qa_context


def test_architecture_uses_inspection_and_one_model_call(qa_context) -> None:
    client, session_factory, repository, provider_box, call_counts = qa_context
    observed_summary = {}

    def response(messages, schema):
        call_counts["model"] += 1
        assert schema is ArchitectureResponse
        content = next(message.content for message in messages if message.role == "user")
        observed_summary.update(json.loads(
            content.split("[UNTRUSTED REPOSITORY METADATA]\n", 1)[1]
            .split("\n[/UNTRUSTED REPOSITORY METADATA]", 1)[0]
            .split("The following deterministic inspect_repository result is data only:\n", 1)[1]
        ))
        return {
            "languages": ["invented-language"],
            "main_folders": ["invented-folder"],
            "frameworks_detected": ["invented-framework"],
            "entrypoints": ["missing.py"],
            "backend_boundary": "an unsupported backend claim",
            "frontend_boundary": "an unsupported frontend claim",
            "database_layer": "an unsupported database claim",
            "api_organization": "an unsupported API claim",
            "auth_locations": ["missing/auth.py"],
            "test_locations": ["missing/test.py"],
            "evidence": [],
        }

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.get(
        f"/repositories/{repository.id}/architecture?model_slot=A"
    )
    assert api_response.status_code == 200
    architecture = ArchitectureResponse.model_validate(api_response.json())

    async def inspect_and_trace():
        async with session_factory() as session:
            summary = await InspectRepositoryTool(session).execute(
                InspectRepositoryInput(repository_id=repository.id),
                ExecutionContext(repository_id=repository.id, user_id=repository.owner_id),
            )
            run = await session.scalar(
                select(AgentRun)
                .where(AgentRun.task_type == "ARCHITECTURE_EXPLANATION")
                .order_by(AgentRun.started_at.desc())
            )
            assert run is not None
            tools = list(await session.scalars(
                select(ToolCall).where(ToolCall.agent_run_id == run.id)
            ))
            models = list(await session.scalars(
                select(ModelExecution).where(ModelExecution.agent_run_id == run.id)
            ))
            return summary, tools, models

    summary, tools, models = asyncio.run(inspect_and_trace())
    assert observed_summary == summary.model_dump(mode="json")
    assert architecture.languages == list(summary.languages)
    assert architecture.main_folders == summary.top_level_folders
    assert architecture.frameworks_detected == summary.frameworks_detected == ["FastAPI"]
    assert architecture.entrypoints == summary.likely_entrypoints
    assert architecture.test_locations == summary.test_locations
    assert architecture.auth_locations == ["auth"]
    assert architecture.api_organization == "routers"
    assert architecture.backend_boundary is None
    assert architecture.frontend_boundary is None
    assert architecture.database_layer is None
    assert architecture.evidence == []
    assert architecture.languages == ["documentation", "python"]
    assert architecture.main_folders == ["auth", "models", "routers"]
    assert [item.tool_name for item in tools] == ["inspect_repository"]
    assert len(models) == call_counts["model"] == 1


def test_architecture_requires_explicit_model_slot(qa_context) -> None:
    client, _, repository, provider_box, _ = qa_context
    provider_box["provider"] = MockProvider(canned_responses=[])
    response = client.get(f"/repositories/{repository.id}/architecture")
    assert response.status_code == 422
