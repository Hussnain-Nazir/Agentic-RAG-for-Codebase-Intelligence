import json
import uuid

import pytest

from app.agent.repair import attempt_repair
from app.evidence.models import (
    ContextTask,
    Evidence,
    EvidenceContext,
    EvidenceQuality,
)
from app.llm.base import LLMResult
from app.schemas.responses import (
    ArchitectureResponse,
    ChangeImpactResponse,
    FlowStep,
    FlowTraceResponse,
    ImpactItem,
    ModelComparisonResponse,
    ModelResult,
    RepositoryAnswer,
)
from app.validation.evidence_validation import validate_citations
from app.validation.schema_validation import SchemaValidationError, validate_schema


def make_evidence(
    *,
    evidence_id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    repository_index_id: uuid.UUID | None = None,
    file_path: str = "auth.py",
    start_line: int = 10,
    end_line: int = 20,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or uuid.uuid4(),
        repository_id=repository_id or uuid.uuid4(),
        repository_index_id=repository_index_id or uuid.uuid4(),
        source_type="CODE",
        file_path=file_path,
        symbol="login",
        start_line=start_line,
        end_line=end_line,
        content_excerpt="def login():\n    return token\n",
        relationship_metadata={},
        retrieval_metadata={"score": 0.9, "signal": "hybrid"},
        external_source_metadata=None,
    )


def make_context(
    evidence: list[Evidence],
    *,
    repository_id: uuid.UUID | None = None,
    repository_index_id: uuid.UUID | None = None,
) -> EvidenceContext:
    current_repository = repository_id or (
        evidence[0].repository_id if evidence else uuid.uuid4()
    )
    current_index = repository_index_id or (
        evidence[0].repository_index_id if evidence else uuid.uuid4()
    )
    return EvidenceContext(
        context_id=uuid.uuid4(),
        repository_id=current_repository,
        repository_index_id=current_index,
        file_line_counts={"auth.py": 100},
        task=ContextTask(query="Explain authentication"),
        task_type="REPOSITORY_QA",
        repository_memory=[],
        evidence=evidence,
        quality=EvidenceQuality.STRONG if evidence else EvidenceQuality.NONE,
        estimated_tokens=100,
    )


def response_fixtures(evidence: Evidence):
    repository_answer = RepositoryAnswer(
        answer="Authentication returns a token.",
        evidence=[evidence],
        confidence="high",
        limitations=None,
    )
    flow_trace = FlowTraceResponse(
        summary="Login flow.",
        steps=[
            FlowStep(
                order=1,
                file="auth.py",
                symbol="login",
                start_line=10,
                end_line=20,
                explanation="Creates a token.",
                relationship_to_next=None,
                unresolved=False,
                evidence_ids=[evidence.evidence_id],
            )
        ],
        evidence=[evidence],
    )
    impact = ChangeImpactResponse(
        requested_change="Change login",
        directly_affected=[
            ImpactItem(
                file="auth.py",
                symbol="login",
                reason="Direct call site.",
                confidence="high",
                evidence_ids=[evidence.evidence_id],
                recommended_action="Update login.",
                tests_to_inspect=["test_auth.py"],
            )
        ],
        likely_indirectly_affected=[],
        evidence=[evidence],
    )
    architecture = ArchitectureResponse(
        summary="The repository contains 1 Python file under backend and uses FastAPI.",
        languages={"python": 1},
        main_folders=["backend"],
        frameworks_detected=["FastAPI"],
        entrypoints=["app.py"],
        backend_boundary="backend",
        frontend_boundary=None,
        database_layer="db.py",
        api_organization="routers",
        auth_locations=["auth.py"],
        test_locations=["test_auth.py"],
        evidence=[evidence],
    )
    comparison = ModelComparisonResponse(
        question="How does login work?",
        evidence_context_id=uuid.uuid4(),
        results=[
            ModelResult(
                slot="A",
                model_name="model-a",
                response=repository_answer.model_dump(mode="json"),
                latency_ms=10,
                input_tokens=20,
                output_tokens=30,
                validation_status="VALID",
                error=None,
            ),
            ModelResult(
                slot="B",
                model_name="model-b",
                response=repository_answer.model_dump(mode="json"),
                latency_ms=12,
                input_tokens=None,
                output_tokens=None,
                validation_status="VALID",
                error=None,
            ),
        ],
    )
    return [repository_answer, flow_trace, impact, architecture, comparison]


def test_well_formed_response_for_every_schema_passes() -> None:
    evidence = make_evidence()

    for response in response_fixtures(evidence):
        validated = validate_schema(response.model_dump_json(), type(response))
        assert validated == response


class CountingProvider:
    model_name = "counting-mock"

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0
        self.messages = []

    async def complete(self, messages, schema, timeout_s):
        del schema, timeout_s
        self.calls += 1
        self.messages.append(messages)
        return LLMResult(
            content=self.content,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            raw_response={},
        )


@pytest.mark.asyncio
async def test_malformed_json_triggers_exactly_one_successful_repair() -> None:
    evidence = make_evidence()
    valid = RepositoryAnswer(
        answer="Repaired",
        evidence=[evidence],
        confidence="high",
        limitations=None,
    )
    raw = "{not valid json"
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(raw, RepositoryAnswer)
    provider = CountingProvider(valid.model_dump_json())

    repaired = await attempt_repair(
        raw,
        RepositoryAnswer,
        exc_info.value,
        provider,
    )

    assert repaired == valid
    assert provider.calls == 1
    assert "Validation error" in provider.messages[0][0].content


@pytest.mark.asyncio
async def test_failed_repair_still_makes_only_one_call() -> None:
    raw = "{not valid json"
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(raw, RepositoryAnswer)
    provider = CountingProvider("{still invalid")

    with pytest.raises(SchemaValidationError):
        await attempt_repair(
            raw,
            RepositoryAnswer,
            exc_info.value,
            provider,
        )

    assert provider.calls == 1


def test_nonexistent_evidence_id_is_removed_and_downgraded() -> None:
    canonical = make_evidence()
    invented = canonical.model_copy(update={"evidence_id": uuid.uuid4()})
    response = RepositoryAnswer(
        answer="Claim",
        evidence=[invented],
        confidence="high",
        limitations=None,
    )

    result = validate_citations(response, make_context([canonical]))

    assert result.downgraded is True
    assert result.response.evidence == []
    assert result.response.confidence == "medium"
    assert result.removed_citations == [str(invented.evidence_id)]


def test_line_range_more_than_five_lines_outside_excerpt_is_removed() -> None:
    canonical = make_evidence(start_line=10, end_line=20)
    drifted = canonical.model_copy(update={"start_line": 16, "end_line": 26})
    response = RepositoryAnswer(
        answer="Claim",
        evidence=[drifted],
        confidence="high",
        limitations=None,
    )

    result = validate_citations(response, make_context([canonical]))

    assert result.downgraded is True
    assert result.response.evidence == []
    assert result.removed_citations == [str(canonical.evidence_id)]


def test_stale_repository_index_evidence_is_rejected() -> None:
    repository_id = uuid.uuid4()
    stale_index = uuid.uuid4()
    current_index = uuid.uuid4()
    stale = make_evidence(
        repository_id=repository_id,
        repository_index_id=stale_index,
    )
    response = RepositoryAnswer(
        answer="Stale claim",
        evidence=[stale],
        confidence="high",
        limitations=None,
    )
    context = make_context(
        [stale],
        repository_id=repository_id,
        repository_index_id=current_index,
    )

    result = validate_citations(response, context)

    assert result.downgraded is True
    assert result.response.evidence == []
    assert result.removed_citations == [str(stale.evidence_id)]
