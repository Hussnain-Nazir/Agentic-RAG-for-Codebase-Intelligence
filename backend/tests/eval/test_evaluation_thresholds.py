"""Deterministic acceptance gates for the full-stack demo repository.

Minimums are chosen for a 25-question fixture with a small, known dependency
graph: Hit@12 and file/symbol recall >= 0.8, ordered flow recall >= 0.8,
direct impact recall/precision >= 0.8, indirect recall >= 0.7 and precision
>= 0.6. Citations and grounded claims must be fully valid; fabricated
references and incorrect resolved transitions are never allowed.
"""

import asyncio
import uuid

from app.agent.investigations.flow_trace import FlowInvestigationState, FlowNode, deterministic_flow_trace
from app.evidence.models import ContextTask, Evidence, EvidenceContext, EvidenceQuality
from app.schemas.responses import ChangeImpactResponse, FlowStep, FlowTraceResponse, ImpactItem, RepositoryAnswer
from app.validation.evidence_validation import validate_citations
from tests.eval.run_evaluation import audit_claims, evaluate


def test_demo_evaluation_clears_ground_truth_thresholds() -> None:
    report = asyncio.run(evaluate())
    metrics = report["metrics"]
    assert report["index_state"] == "READY"
    assert 20 <= report["question_count"] <= 30
    assert {item["category"] for item in report["questions"]} == {
        "symbol", "qa", "architecture", "flow", "impact"
    }
    assert metrics["retrieval_hit_at_12"] >= 0.8
    assert metrics["expected_file_recall"] >= 0.8
    assert metrics["expected_symbol_recall"] >= 0.8
    assert metrics["citation_validity_rate"] == 1.0
    assert metrics["evidence_groundedness_rate"] == 1.0
    assert metrics["invalid_reference_rate"] == 0.0
    assert metrics["expected_step_recall"] >= 0.8
    assert metrics["step_order_correct"] == 1.0
    assert metrics["direct_recall"] >= 0.8
    assert metrics["direct_precision"] >= 0.8
    assert metrics["indirect_recall"] >= 0.7
    assert metrics["indirect_precision"] >= 0.6
    assert metrics["architecture_languages_match"] == 1.0
    assert metrics["architecture_frameworks_match"] == 1.0
    assert all(item["tool_count"] <= 8 for item in report["questions"])
    assert not report["unsuccessful_questions"], report["unsuccessful_questions"]
    assert all(not item["errors"] for item in report["questions"])


def _evidence(start: int, end: int) -> Evidence:
    return Evidence(
        evidence_id=uuid.uuid4(), repository_id=uuid.UUID(int=1),
        repository_index_id=uuid.UUID(int=2), source_type="CODE",
        file_path="backend/demo_app/security.py", symbol="create_access_token",
        start_line=start, end_line=end, content_excerpt="def create_access_token(): pass",
    )


def _context(items: list[Evidence]) -> EvidenceContext:
    return EvidenceContext(
        context_id=uuid.uuid4(), repository_id=uuid.UUID(int=1),
        repository_index_id=uuid.UUID(int=2),
        file_line_counts={"backend/demo_app/security.py": 30},
        task=ContextTask(query="Trace token"), task_type="FLOW_TRACE",
        repository_memory=[], evidence=items, quality=EvidenceQuality.INCOMPLETE,
        estimated_tokens=100,
    )


def test_audit_rejects_unsupported_claims_and_fabricated_references() -> None:
    source = _evidence(1, 3)
    context = _context([source])
    answer = RepositoryAnswer(
        answer="The app sends passwords to an external payment gateway.",
        evidence=[source], confidence="high", limitations=None,
    )
    assert "unsupported answer claim" in audit_claims(
        "qa", answer, context, None, {source.file_path: 30},
        {(source.file_path, "create_access_token")},
    )

    fabricated = FlowTraceResponse(
        summary="Invented flow", evidence=[source], steps=[
            FlowStep(order=1, file="missing.py", symbol="invented", start_line=1,
                     end_line=3, explanation="Invented step", relationship_to_next=None,
                     unresolved=False, evidence_ids=[source.evidence_id]),
        ],
    )
    errors = audit_claims(
        "flow", fabricated, context, {"nodes": [], "edges": []},
        {source.file_path: 30}, {(source.file_path, "create_access_token")},
    )
    assert any("fabricated flow" in error for error in errors)

    second = Evidence(
        evidence_id=uuid.uuid4(), repository_id=source.repository_id,
        repository_index_id=source.repository_index_id, source_type="CODE",
        file_path=source.file_path, symbol="verify_password", start_line=4,
        end_line=6, content_excerpt="def verify_password(): pass",
    )
    wrong_link = FlowTraceResponse(
        summary="Unsupported link", evidence=[source, second], steps=[
            FlowStep(order=1, file=source.file_path, symbol="create_access_token",
                     start_line=1, end_line=3, explanation="Observed create_access_token.",
                     relationship_to_next="CALLS", unresolved=False,
                     evidence_ids=[source.evidence_id]),
            FlowStep(order=2, file=second.file_path, symbol="verify_password",
                     start_line=4, end_line=6, explanation="Observed verify_password.",
                     relationship_to_next=None, unresolved=False,
                     evidence_ids=[second.evidence_id]),
        ],
    )
    errors = audit_claims(
        "flow", wrong_link, _context([source, second]),
        {"nodes": [], "edges": []}, {source.file_path: 30},
        {(source.file_path, "create_access_token"), (source.file_path, "verify_password")},
    )
    assert "resolved transition absent from observed graph" in errors

    impact = ChangeImpactResponse(
        requested_change="change token", directly_affected=[ImpactItem(
            file="missing.py", symbol="invented", reason="Unsupported reason",
            confidence="high", evidence_ids=[source.evidence_id],
            recommended_action="None", tests_to_inspect=[],
        )], likely_indirectly_affected=[], evidence=[source],
    )
    errors = audit_claims(
        "impact", impact, context,
        {"directly_affected": [], "likely_indirectly_affected": []},
        {source.file_path: 30}, {(source.file_path, "create_access_token")},
    )
    assert "unsupported impact claim" in errors


def test_flow_fallback_keeps_only_citations_matching_its_line_range() -> None:
    full = _evidence(1, 20)
    narrow = _evidence(16, 20)
    state = FlowInvestigationState()
    state.add_node(FlowNode(
        node_id="token", symbol="create_access_token", symbol_id=None,
        file_path=full.file_path, start_line=1, end_line=20,
        evidence_ids=[full.evidence_id, narrow.evidence_id],
    ))
    result = deterministic_flow_trace(state, [full, narrow])
    assert result.steps[0].evidence_ids == [full.evidence_id]
    assert validate_citations(result, _context([full, narrow])).removed_citations == []
