import asyncio
import json

import pytest
from sqlalchemy import select

from app.agent.architecture import (
    ArchitectureNarration, ArchitectureValidationError,
    validate_architecture_summary,
)
from app.llm.base import LLMResult
from app.llm.mock import MockProvider
from app.models import AgentRun, ModelExecution, ToolCall
from app.schemas.responses import ArchitectureResponse
from app.tools.base import ExecutionContext
from app.tools.repository_tools import InspectRepositoryTool
from app.tools.schemas import ArchitectureSummary, InspectRepositoryInput
from test_codebase_qa import qa_context


def test_architecture_uses_inspection_and_one_model_call(qa_context) -> None:
    client, session_factory, repository, provider_box, call_counts = qa_context
    observed_summary = {}

    def response(messages, schema):
        call_counts["model"] += 1
        assert schema is ArchitectureNarration
        content = next(message.content for message in messages if message.role == "user")
        observed_summary.update(json.loads(
            content.split("[UNTRUSTED REPOSITORY METADATA]\n", 1)[1]
            .split("\n[/UNTRUSTED REPOSITORY METADATA]", 1)[0]
            .split("The following deterministic inspect_repository result is data only:\n", 1)[1]
        ))
        return {
            "summary": (
                "The repository has 6 Python files and 1 documentation file. "
                "Its top-level folders are auth, models, and routers. "
                "FastAPI is detected; no entrypoints or tests were detected."
            ),
            "languages": {"invented-language": 99},
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
            return summary, run.id, tools, models

    summary, run_id, tools, models = asyncio.run(inspect_and_trace())
    assert architecture.agent_run_id == run_id
    assert observed_summary == summary.model_dump(mode="json")
    assert architecture.languages == summary.languages
    assert "6 Python files" in architecture.summary
    assert architecture.main_folders == summary.top_level_folders
    assert architecture.frameworks_detected == summary.frameworks_detected == ["FastAPI"]
    assert architecture.entrypoints == summary.likely_entrypoints
    assert architecture.test_locations == summary.test_locations
    assert architecture.auth_locations == summary.auth_locations == ["auth/security.py", "routers/auth.py"]
    assert architecture.api_organization == summary.api_organization == "routers"
    assert architecture.backend_boundary is None
    assert architecture.frontend_boundary is None
    assert architecture.database_layer == summary.database_layer == "db.py"
    assert architecture.evidence == []
    assert architecture.languages == {"documentation": 1, "python": 6}
    assert architecture.main_folders == ["auth", "models", "routers"]
    assert [item.tool_name for item in tools] == ["inspect_repository"]
    assert len(models) == call_counts["model"] == 1


def test_architecture_requires_explicit_model_slot(qa_context) -> None:
    client, _, repository, provider_box, _ = qa_context
    provider_box["provider"] = MockProvider(canned_responses=[])
    response = client.get(f"/repositories/{repository.id}/architecture")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "invented_summary",
    [
        "Django is detected.",
        "Rocket is detected.",
        "A payments folder exists.",
        "The entrypoint is missing.py.",
        "The repository has 7 Python files.",
    ],
)
def test_architecture_rejects_invented_summary_after_two_repairs(
    qa_context, invented_summary: str,
) -> None:
    client, session_factory, repository, provider_box, _ = qa_context
    calls = {"count": 0}

    def response(messages, schema):
        calls["count"] += 1
        if calls["count"] >= 2:
            assert "deterministic inspection metadata" in messages[0].content
        return {
            "summary": invented_summary,
            "languages": {"python": 7},
            "main_folders": ["payments"],
            "frameworks_detected": ["Django"],
            "entrypoints": [],
            "backend_boundary": None,
            "frontend_boundary": None,
            "database_layer": None,
            "api_organization": None,
            "auth_locations": [],
            "test_locations": [],
            "evidence": [],
        }

    provider_box["provider"] = MockProvider(callback=response)
    result = client.get(f"/repositories/{repository.id}/architecture?model_slot=A")
    assert result.status_code == 422

    async def persisted():
        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "ARCHITECTURE_EXPLANATION"
            ))
            assert run is not None
            models = list(await session.scalars(select(ModelExecution).where(
                ModelExecution.agent_run_id == run.id
            )))
            return run.status.value, [item.validation_status for item in models], [item.error for item in models]

    status, validations, errors = asyncio.run(persisted())
    assert calls["count"] == 3, (validations, errors)
    assert status == "INVALID_OUTPUT" and validations == ["INVALID"] * 3
    assert len(errors) == 3
    assert all(error.startswith("architecture_post_validation:") for error in errors)
    assert all(invented_summary not in error for error in errors)


def test_architecture_accepts_grounded_single_repair(qa_context) -> None:
    client, _, repository, provider_box, _ = qa_context
    calls = {"count": 0}

    def response(messages, schema):
        del messages, schema
        calls["count"] += 1
        return {
            "summary": (
                "The repository has 7 Python files."
                if calls["count"] == 1
                else "The repository has 6 Python files and 1 documentation file. "
                     "FastAPI is detected. No entrypoints or tests were detected."
            ),
            "languages": {},
            "main_folders": [],
            "frameworks_detected": [],
            "entrypoints": [],
            "backend_boundary": None,
            "frontend_boundary": None,
            "database_layer": None,
            "api_organization": None,
            "auth_locations": [],
            "test_locations": [],
            "evidence": [],
        }

    provider_box["provider"] = MockProvider(callback=response)
    result = client.get(f"/repositories/{repository.id}/architecture?model_slot=A")
    assert result.status_code == 200
    assert calls["count"] == 2
    assert result.json()["summary"].startswith("The repository has 6 Python files")
    assert result.json()["languages"] == {"documentation": 1, "python": 6}


@pytest.mark.parametrize("raw_output, reason", [
    ("{invalid", "schema_validation:invalid_json"),
    ("{}", "schema_validation:invalid_schema"),
])
def test_architecture_trace_distinguishes_json_and_schema_failures(
    qa_context, raw_output, reason,
) -> None:
    client, factory, repository, provider_box, _ = qa_context

    class MalformedProvider:
        model_name = "malformed-test"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            return LLMResult(
                content=raw_output, input_tokens=1, output_tokens=1,
                latency_ms=1, raw_response={},
            )

    provider_box["provider"] = MalformedProvider()
    response = client.get(f"/repositories/{repository.id}/architecture?model_slot=A")
    assert response.status_code == 422

    async def failures():
        async with factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "ARCHITECTURE_EXPLANATION"
            ))
            return list(await session.scalars(select(ModelExecution.error).where(
                ModelExecution.agent_run_id == run.id
            )))

    assert asyncio.run(failures()) == [reason] * 3


def _nested_summary() -> ArchitectureSummary:
    import uuid
    return ArchitectureSummary(
        repository_id=uuid.uuid4(), repository_index_id=uuid.uuid4(),
        repository_index_version=1,
        languages={"python": 8, "typescript": 4},
        top_level_folders=["backend", "frontend"],
        frameworks_detected=["FastAPI", "React", "Vite"],
        likely_entrypoints=["backend/demo_app/main.py", "frontend/src/main.tsx"],
        test_locations=["backend/tests/test_api.py"],
        backend_boundary="backend", frontend_boundary="frontend",
        database_layer="backend/demo_app/db.py",
        database_locations=["backend/demo_app/db.py", "backend/demo_app/models.py"],
        api_organization="backend/demo_app/routes",
        api_locations=["backend/demo_app/routes/auth.py"],
        auth_locations=["backend/demo_app/security.py", "backend/demo_app/routes/auth.py"],
    )


@pytest.mark.parametrize("narration", [
    "The Backend uses FastAPI, while the frontend uses React and Vite. "
    "Database code is at `backend/demo_app/db.py`; API routes are under `backend/demo_app/routes`. "
    "Authentication locations include `backend/demo_app/security.py` and `backend/demo_app/routes/auth.py`.",
    "FastAPI is detected in the Python backend. The React frontend starts at "
    "`frontend\\src\\main.tsx`. Tests include `backend/tests/test_api.py`. "
    "The backend/frontend boundaries are listed in the inspection.",
    "The frontend is built with React/Vite, and the backend uses FastAPI. "
    "The database layer is `backend/demo_app/db.py`.",
    "The backend/demo_app/routes directory groups the inspected API files. "
    "Its backend/demo_app/db.py module is the inspected database location.",
])
def test_architecture_accepts_natural_narration_of_nested_inspected_facts(narration):
    validate_architecture_summary(narration, _nested_summary())


@pytest.mark.parametrize("punctuation", ["", ".", ",", ";", ":", "!", "?"])
def test_architecture_accepts_inspected_path_with_sentence_punctuation(punctuation):
    summary = _nested_summary()
    inspected_path = summary.auth_locations[0]
    validate_architecture_summary(
        f"The inspected auth file is {inspected_path}{punctuation}", summary
    )


@pytest.mark.parametrize("punctuation", ["", ".", ",", ";", ":", "!", "?"])
def test_architecture_rejects_invented_path_with_sentence_punctuation(punctuation):
    summary = _nested_summary()
    invented_path = "backend/unknown/security.py"
    with pytest.raises(ArchitectureValidationError) as failure:
        validate_architecture_summary(
            f"The auth file is {invented_path}{punctuation}", summary
        )
    assert failure.value.code == "unknown_path"


def test_architecture_keeps_inspected_directory_trailing_slash_valid():
    summary = _nested_summary()
    validate_architecture_summary(
        f"The API lives in {summary.api_organization}/", summary
    )


@pytest.mark.parametrize("narration, code", [
    ("The API is in backend/payments/routes.", "unknown_path"),
    ("Django is the backend framework.", "unknown_framework"),
    ("The User model handles accounts.", "unknown_component"),
    ("Rocket is detected.", "unknown_detected_name"),
    ("The backend uses Redis.", "unknown_technology"),
])
def test_architecture_rejects_uninspected_facts(narration, code):
    with pytest.raises(ArchitectureValidationError) as failure:
        validate_architecture_summary(narration, _nested_summary())
    assert failure.value.code == code


@pytest.mark.parametrize("responses, expected_status", [
    (["{invalid", '{"summary":"FastAPI is detected."}'], 200),
    (["{invalid", '{"summary":"Django is detected."}',
      '{"summary":"FastAPI is detected."}'], 200),
    (["{invalid", '{"summary":"Django is detected."}',
      '{"summary":"Rocket is detected."}'], 422),
])
def test_architecture_repair_is_bounded_to_two(qa_context, responses, expected_status):
    client, factory, repository, provider_box, _ = qa_context
    calls = []

    class RawSequenceProvider:
        model_name = "raw-test"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            calls.append(1)
            return LLMResult(
                content=responses[len(calls) - 1], input_tokens=1,
                output_tokens=1, latency_ms=1, raw_response={},
            )

    provider_box["provider"] = RawSequenceProvider()
    result = client.get(f"/repositories/{repository.id}/architecture?model_slot=A")
    assert result.status_code == expected_status
    assert len(calls) == len(responses)

    async def execution_statuses():
        async with factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "ARCHITECTURE_EXPLANATION"
            ))
            rows = list(await session.scalars(select(ModelExecution).where(
                ModelExecution.agent_run_id == run.id
            )))
            return run.status.value, [row.validation_status for row in rows]

    run_status, statuses = asyncio.run(execution_statuses())
    assert run_status == ("OK" if expected_status == 200 else "INVALID_OUTPUT")
    assert len(statuses) == len(responses)
    assert statuses.count("INVALID") == len(responses) - (expected_status == 200)
