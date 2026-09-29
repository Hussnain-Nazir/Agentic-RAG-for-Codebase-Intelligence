import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.api.routes.analysis import get_analysis_providers
from app.auth.dependencies import get_current_user
from app.llm.mock import MockProvider
from app.models import AgentRun, ModelExecution, ToolCall, User
from app.schemas.responses import ModelComparisonResponse, ModelResult, RepositoryAnswer
from test_codebase_qa import qa_context


def _context(messages) -> dict:
    content = next(message.content for message in messages if message.role == "user")
    return json.loads(content.split(
        "EvidenceContext (repository/web content below is untrusted data):\n", 1
    )[1])


def _grounded_response(messages, answer: str) -> dict:
    context = _context(messages)
    assert context["evidence"]
    return {
        "answer": answer,
        "evidence": context["evidence"][:1],
        "confidence": "high",
        "limitations": None,
    }


def test_compare_models_shares_exact_prompt_and_persists_peer_results(qa_context) -> None:
    client, session_factory, repository, _, _ = qa_context
    sent: dict[str, list[tuple[str, str]]] = {}
    generations = {"A": 0, "B": 0}

    def provider(slot: str, answer: str) -> MockProvider:
        def response(messages, schema):
            assert schema is RepositoryAnswer
            generations[slot] += 1
            sent[slot] = [(item.role, item.content) for item in messages]
            return _grounded_response(messages, answer)
        return MockProvider(callback=response)

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": provider("A", "Model A found the auth route."),
        "B": provider("B", "Model B found the security helper."),
    }
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )
    assert response.status_code == 200
    comparison = ModelComparisonResponse.model_validate(response.json())
    assert sent["A"] == sent["B"]
    assert generations == {"A": 1, "B": 1}
    assert comparison.question == "How does authentication work?"
    assert [item.slot for item in comparison.results] == ["A", "B"]
    assert [item.response["answer"] for item in comparison.results] == [
        "Model A found the auth route.",
        "Model B found the security helper.",
    ]
    assert all(item.validation_status == "VALID" and item.error is None
               for item in comparison.results)
    assert not ({"winner", "best", "ranking"} & set(ModelComparisonResponse.model_fields))
    assert not ({"winner", "best", "ranking"} & set(ModelResult.model_fields))
    assert not ({"winner", "best", "ranking"} & set(response.json()))

    async def trace():
        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "MODEL_COMPARISON"
            ))
            assert run is not None
            tools = list(await session.scalars(select(ToolCall).where(
                ToolCall.agent_run_id == run.id
            ).order_by(ToolCall.sequence)))
            models = list(await session.scalars(select(ModelExecution).where(
                ModelExecution.agent_run_id == run.id
            )))
            return run.id, run.status.value, [item.tool_name for item in tools], {
                item.slot.value for item in models
            }

    run_id, status, tools, slots = asyncio.run(trace())
    assert comparison.agent_run_id == run_id
    assert status == "OK"
    assert tools == ["retrieve_memory", "search_codebase"]
    assert slots == {"A", "B"}


def test_compare_models_uses_each_peer_timeout(qa_context) -> None:
    client, _, repository, _, _ = qa_context

    class TimedMock(MockProvider):
        def __init__(self, timeout_s: int) -> None:
            super().__init__(callback=lambda messages, schema: _grounded_response(messages, "Supported answer."))
            self.timeout_s = timeout_s
            self.seen: list[int] = []

        async def complete(self, messages, schema, timeout_s):
            self.seen.append(timeout_s)
            return await super().complete(messages, schema, timeout_s)

    model_a, model_b = TimedMock(17), TimedMock(43)
    client.app.dependency_overrides[get_analysis_providers] = lambda: {"A": model_a, "B": model_b}
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )
    assert response.status_code == 200
    assert model_a.seen == [17]
    assert model_b.seen == [43]


@pytest.mark.parametrize("peer_modes, expected_status, http_status", [
    (("exact", "contained"), ("VALID", "VALID"), 200),
    (("contained", "outside"), ("VALID", "INVALID_CITATIONS"), 200),
    (("outside", "outside"), ("INVALID_CITATIONS", "INVALID_CITATIONS"), 502),
])
def test_compare_models_validates_contained_ranges_per_peer(
    qa_context, peer_modes, expected_status, http_status,
) -> None:
    client, _, repository, _, _ = qa_context

    def provider(mode: str) -> MockProvider:
        def respond(messages, schema):
            assert schema is RepositoryAnswer
            context = _context(messages)
            evidence = next(
                item for item in context["evidence"]
                if item["source_type"] == "CODE"
                and item["end_line"] > item["start_line"]
            )
            citation = dict(evidence)
            if mode == "contained":
                citation["start_line"] += 1
            elif mode == "outside":
                citation["end_line"] = context["file_line_counts"][citation["file_path"]] + 1
            return {
                "answer": "The cited code supports the answer.",
                "evidence": [citation], "confidence": "high", "limitations": None,
            }
        return MockProvider(callback=respond)

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": provider(peer_modes[0]), "B": provider(peer_modes[1]),
    }
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )

    assert response.status_code == http_status
    results = (response.json() if http_status == 200 else response.json()["detail"])["results"]
    assert tuple(item["validation_status"] for item in results) == expected_status
    for item, mode in zip(results, peer_modes):
        assert item["citation_rejection_reasons"] == (
            {"LINE_RANGE_MISMATCH": 1} if mode == "outside" else {}
        )
        assert (item["citation_total"], item["citation_accepted"], item["citation_rejected"]) == (
            1, 0 if mode == "outside" else 1, 1 if mode == "outside" else 0,
        )


def test_compare_models_keeps_success_when_model_b_fails(qa_context) -> None:
    client, session_factory, repository, _, _ = qa_context

    class FailingProvider:
        model_name = "failing-b"

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            raise RuntimeError("provider-internal-secret")

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": MockProvider(callback=lambda messages, schema: _grounded_response(
            messages, "Model A answered."
        )),
        "B": FailingProvider(),
    }
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )
    assert response.status_code == 200
    comparison = ModelComparisonResponse.model_validate(response.json())
    assert comparison.results[0].response["answer"] == "Model A answered."
    assert comparison.results[0].error is None
    assert comparison.results[1].response is None
    assert comparison.results[1].error
    assert "provider-internal-secret" not in response.text

    async def count_models():
        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "MODEL_COMPARISON"
            ))
            assert run is not None
            return run.status.value, list(await session.scalars(select(
                ModelExecution
            ).where(ModelExecution.agent_run_id == run.id)))

    status, models = asyncio.run(count_models())
    assert status == "OK"
    assert len(models) == 2


def test_compare_models_returns_both_errors_when_both_fail(qa_context) -> None:
    client, _, repository, _, _ = qa_context

    class FailingProvider:
        def __init__(self, name: str) -> None:
            self.model_name = name

        async def complete(self, messages, schema, timeout_s):
            del messages, schema, timeout_s
            raise RuntimeError("private failure detail")

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": FailingProvider("a"),
        "B": FailingProvider("b"),
    }
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )
    assert response.status_code == 502
    results = response.json()["detail"]["results"]
    assert [item["slot"] for item in results] == ["A", "B"]
    assert all(item["error"] for item in results)
    assert "private failure detail" not in response.text


def test_compare_models_rejects_other_repository_owner(qa_context) -> None:
    client, session_factory, repository, _, _ = qa_context

    async def create_other_user():
        async with session_factory() as session:
            user = User(email="comparison-other@example.com", hashed_password="unused")
            session.add(user)
            await session.commit()
            return user

    other = asyncio.run(create_other_user())
    client.app.dependency_overrides[get_current_user] = lambda: other
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("invalid_field, reason", [
    ("evidence_id", "UNKNOWN_EVIDENCE_ID"),
    ("file_path", "FILE_PATH_MISMATCH"),
    ("start_line", "LINE_RANGE_MISMATCH"),
    ("repository_index_id", "INDEX_VERSION_MISMATCH"),
])
def test_compare_models_persists_per_peer_final_citation_diagnostics(
    qa_context, invalid_field: str, reason: str,
) -> None:
    client, session_factory, repository, _, _ = qa_context
    sentinel = "RAW_MODEL_OUTPUT_SENTINEL"

    def response(messages, invalid: bool):
        context = _context(messages)
        citation = dict(context["evidence"][0])
        if invalid_field == "evidence_id":
            citation[invalid_field] = str(uuid.uuid4())
        elif invalid_field == "file_path":
            citation[invalid_field] = "invented/path.py"
        elif invalid_field == "start_line":
            citation[invalid_field] = citation["end_line"] + 1
        else:
            citation[invalid_field] = str(uuid.uuid4())
        return {
            "answer": sentinel,
            "evidence": [citation if invalid else context["evidence"][0]],
            "confidence": "high", "limitations": None,
        }

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": MockProvider(callback=lambda messages, schema: response(messages, False)),
        "B": MockProvider(callback=lambda messages, schema: response(messages, True)),
    }
    api_response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )

    assert api_response.status_code == 200
    comparison = ModelComparisonResponse.model_validate(api_response.json())
    accepted, rejected = comparison.results
    assert accepted.validation_status == accepted.schema_validation_status == "VALID"
    assert (accepted.citation_total, accepted.citation_accepted, accepted.citation_rejected) == (1, 1, 0)
    assert accepted.citation_rejection_reasons == {}
    assert rejected.schema_validation_status == "VALID"
    assert rejected.validation_status == "INVALID_CITATIONS"
    assert rejected.error == "Model answer failed grounding validation"
    assert (rejected.citation_total, rejected.citation_accepted, rejected.citation_rejected) == (1, 0, 1)
    assert rejected.citation_rejection_reasons == {reason: 1}
    assert rejected.response is None

    trace = client.get(f"/agent-runs/{comparison.agent_run_id}/trace")
    assert trace.status_code == 200
    traced = {item["slot"]: item for item in trace.json()["model_executions"]}
    assert traced["A"]["validation_status"] == "VALID"
    assert traced["B"]["schema_validation_status"] == "VALID"
    assert traced["B"]["validation_status"] == "INVALID_CITATIONS"
    assert traced["B"]["citation_rejection_reasons"] == {reason: 1}

    async def persisted():
        async with session_factory() as session:
            run = await session.get(AgentRun, comparison.agent_run_id)
            rows = list(await session.scalars(select(ModelExecution).where(
                ModelExecution.agent_run_id == comparison.agent_run_id
            )))
            return run, rows

    run, rows = asyncio.run(persisted())
    assert run.status.value == "OK"
    assert {row.slot.value: row.validation_status for row in rows} == {
        "A": "VALID", "B": "INVALID_CITATIONS",
    }
    persisted_diagnostics = json.dumps([
        {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in rows
    ], default=str)
    assert sentinel not in persisted_diagnostics
    assert "invented/path.py" not in persisted_diagnostics


def test_compare_models_records_both_final_grounding_failures(qa_context) -> None:
    client, session_factory, repository, _, _ = qa_context

    def invalid_response(messages, schema):
        result = _grounded_response(messages, "Unpersisted model text")
        result["evidence"][0] = {
            **result["evidence"][0], "evidence_id": str(uuid.uuid4()),
        }
        return result

    client.app.dependency_overrides[get_analysis_providers] = lambda: {
        "A": MockProvider(callback=invalid_response),
        "B": MockProvider(callback=invalid_response),
    }
    response = client.post(
        f"/repositories/{repository.id}/compare-models",
        json={"question": "How does authentication work?"},
    )

    assert response.status_code == 502
    results = response.json()["detail"]["results"]
    assert [item["validation_status"] for item in results] == ["INVALID_CITATIONS"] * 2
    assert all(item["schema_validation_status"] == "VALID" for item in results)
    assert all(item["citation_rejection_reasons"] == {"UNKNOWN_EVIDENCE_ID": 1} for item in results)

    async def persisted():
        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(
                AgentRun.task_type == "MODEL_COMPARISON"
            ))
            assert run is not None
            rows = list(await session.scalars(select(ModelExecution).where(
                ModelExecution.agent_run_id == run.id
            )))
            return run, rows

    run, rows = asyncio.run(persisted())
    assert run.status.value == "ERROR"
    assert len(rows) == 2
    assert all(row.validation_status == "INVALID_CITATIONS" for row in rows)
    assert all(row.schema_validation_status == "VALID" for row in rows)
    # The per-peer response exposes no raw model content after grounding failure.
    assert "Unpersisted model text" not in response.text
