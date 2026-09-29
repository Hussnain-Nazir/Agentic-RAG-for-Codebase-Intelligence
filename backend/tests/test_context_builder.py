import hashlib
import uuid
from types import SimpleNamespace

import pytest

from app.evidence.builder import build_evidence
from app.evidence.context_builder import MAX_CONTEXT_TOKENS, MAX_EVIDENCE_ITEMS, ContextBuilder
from app.evidence.models import (
    ContextTask,
    EvidenceContext,
    EvidenceQuality,
    RepositoryMemoryContextItem,
    WebEvidenceItem,
)
from app.evidence.quality import (
    MIN_SEMANTIC_EVIDENCE_SCORE,
    classify_evidence_quality,
)
from app.models import CodeChunk, CodeChunkType
from app.retrieval.models import RankedChunk
import app.evidence as evidence_package


def make_candidate(
    number: int,
    *,
    score: float,
    content: str,
    file_path: str | None = None,
    symbol_name: str | None = None,
    metadata: dict | None = None,
    signal: str = "hybrid",
    contributing_signals: tuple[str, ...] | None = None,
    raw_signal_scores: dict[str, float] | None = None,
    relationship_metadata: dict | None = None,
) -> RankedChunk:
    path = file_path or f"src/file_{number:02}.py"
    chunk = CodeChunk(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"context-builder:{number}:{path}"),
        repository_id=uuid.UUID(int=1),
        repository_index_id=uuid.UUID(int=2),
        file_id=uuid.uuid5(uuid.NAMESPACE_URL, f"context-file:{path}"),
        file_path=path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name=symbol_name,
        symbol_type="FUNCTION" if symbol_name else None,
        parent_symbol=None,
        start_line=number * 20 + 1,
        end_line=number * 20 + max(len(content.splitlines()), 1),
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        embedding=None,
        chunk_metadata={"source_type": "CODE", **(metadata or {})},
    )
    return RankedChunk(
        chunk=chunk,
        raw_score=score,
        signal=signal,
        final_score=score,
        raw_signal_scores=raw_signal_scores or {"semantic": score},
        contributing_signals=contributing_signals or ("semantic",),
        relationship_metadata=relationship_metadata or {},
    )


def test_abundant_matches_produce_strong_bounded_provider_independent_context() -> None:
    candidates = [
        make_candidate(
            number,
            score=0.95 - number * 0.03,
            content=f"def useful_{number}():\n    return 'authentication evidence {number}'\n",
            symbol_name=f"useful_{number}",
        )
        for number in range(6)
    ]
    memory = [
        RepositoryMemoryContextItem(
            topic="authentication",
            content="Authentication uses a login route.",
            tags=["auth"],
        ),
        RepositoryMemoryContextItem(
            topic="billing",
            content="Billing is unrelated.",
        ),
    ]

    context = ContextBuilder().build(
        ContextTask(query="Explain authentication", extracted_keywords=["auth"]),
        "REPOSITORY_QA",
        memory,
        candidates,
        [],
        web_evidence=[
            WebEvidenceItem(
                title="Official documentation",
                url="https://docs.example.test/auth",
                snippet="Current authentication documentation.",
                source_domain="docs.example.test",
                score=0.8,
            )
        ],
    )

    assert context.quality is EvidenceQuality.STRONG
    assert context.estimated_tokens <= MAX_CONTEXT_TOKENS
    assert len(context.evidence) == 7
    assert all(
        item.file_path is not None
        and item.start_line is not None
        and item.end_line is not None
        for item in context.evidence
        if item.source_type != "WEB"
    )
    assert [item.topic for item in context.repository_memory] == ["authentication"]
    assert EvidenceContext.model_fields.keys().isdisjoint(
        {"provider", "llm_provider", "model_name", "base_url"}
    )


def test_no_matches_produces_none_quality_and_empty_evidence() -> None:
    context = ContextBuilder().build(
        "unknown behavior",
        "REPOSITORY_QA",
        [],
        [],
        [],
    )

    assert context.quality is EvidenceQuality.NONE
    assert context.evidence == []
    assert context.estimated_tokens == 0


def test_task_keywords_accept_one_string_and_ignore_non_iterable_values() -> None:
    builder = ContextBuilder()
    from_mapping = builder.build(
        {"query": "Explain authentication", "extracted_keywords": "auth"},
        "REPOSITORY_QA", [], [], [],
    )
    from_object = builder.build(
        SimpleNamespace(query="Explain authentication", extracted_keywords=17),
        "REPOSITORY_QA", [], [], [],
    )

    assert from_mapping.task.extracted_keywords == ["auth"]
    assert from_object.task.extracted_keywords == []


def test_evidence_package_exports_have_one_complete_public_list() -> None:
    assert len(evidence_package.__all__) == len(set(evidence_package.__all__))
    assert "Evidence" in evidence_package.__all__
    assert "ContextBuilder" in evidence_package.__all__


def test_duplicate_route_paths_in_different_files_are_conflicting() -> None:
    first = make_candidate(
        1,
        score=0.9,
        content='@router.get("/health")\ndef health(): return {"ok": True}',
        file_path="api/first.py",
        symbol_name="health_first",
        metadata={"api_routes": ['@router.get("/health")']},
    )
    second = make_candidate(
        2,
        score=0.85,
        content='@router.get("/health")\ndef health(): return {"status": "ok"}',
        file_path="api/second.py",
        symbol_name="health_second",
        metadata={"api_routes": ['@router.get("/health")']},
    )

    context = ContextBuilder().build(
        "Where is the health route?",
        "REPOSITORY_QA",
        [],
        [first, second],
        [],
    )

    assert context.quality is EvidenceQuality.CONFLICTING
    assert len(context.evidence) == 2


def test_large_candidate_set_drops_lowest_ranked_whole_chunks() -> None:
    candidates = [
        make_candidate(
            number,
            score=1.0 - number * 0.01,
            content=f"chunk-{number:02}:" + (chr(65 + number) * 3_390),
        )
        for number in range(15)
    ]
    original = {
        candidate.chunk.file_path: candidate.chunk.content for candidate in candidates
    }

    context = ContextBuilder().build(
        "large evidence set",
        "REPOSITORY_QA",
        [],
        candidates,
        [],
    )

    expected_paths: list[str] = []
    used = 0
    for candidate in candidates[:MAX_EVIDENCE_ITEMS]:
        size = len(candidate.chunk.content)
        if used + size > MAX_CONTEXT_TOKENS * 4:
            break
        expected_paths.append(candidate.chunk.file_path)
        used += size

    assert [item.file_path for item in context.evidence] == expected_paths
    assert len(context.evidence) < len(candidates)
    assert context.estimated_tokens <= MAX_CONTEXT_TOKENS
    for item in context.evidence:
        assert item.content_excerpt == original[item.file_path]


def test_evidence_item_limit_is_sixteen() -> None:
    candidates = [
        make_candidate(number, score=1.0 - number * 0.01,
                       content=f"def useful_{number}(): return {number}")
        for number in range(20)
    ]
    context = ContextBuilder().build("useful functions", "REPOSITORY_QA", [], candidates, [])
    assert MAX_EVIDENCE_ITEMS == 16
    assert len(context.evidence) == 16


def test_external_doc_context_reserves_web_evidence_with_full_local_candidate_set() -> None:
    candidates = [
        make_candidate(number, score=1.0 - number * 0.01,
                       content=f"def useful_{number}(): return {number}")
        for number in range(20)
    ]
    context = ContextBuilder().build(
        "Compare implementation with official docs", "EXTERNAL_DOC_QUERY",
        [], candidates, [], [WebEvidenceItem(
            title="Official documentation", url="https://docs.example.test/current",
            snippet="Current documented behavior.", source_domain="docs.example.test",
        )],
    )

    assert len(context.evidence) == MAX_EVIDENCE_ITEMS
    assert context.evidence[0].source_type == "CODE"
    assert context.evidence[-1].source_type == "WEB"
    assert context.evidence[-1].external_source_metadata["url"] == "https://docs.example.test/current"
    assert context.estimated_tokens <= MAX_CONTEXT_TOKENS


def test_structural_relationship_metadata_is_preserved() -> None:
    candidate = make_candidate(
        1,
        score=0.7,
        content="def caller(): return callee()",
        signal="structural",
        relationship_metadata={"related_to": "callee", "kind": "caller"},
    )

    context = ContextBuilder().build(
        "trace caller",
        "FLOW_TRACE",
        [],
        [],
        [candidate],
    )

    assert context.evidence[0].relationship_metadata == {
        "related_to": "callee",
        "kind": "caller",
    }


def test_evidence_quality_rejects_low_semantic_only_matches() -> None:
    evidence = build_evidence(
        [
            make_candidate(
                1,
                score=MIN_SEMANTIC_EVIDENCE_SCORE - 0.01,
                content="unrelated",
                signal="semantic",
            )
        ]
    )

    assert classify_evidence_quality(evidence) is EvidenceQuality.NONE


def test_evidence_quality_accepts_a_queried_symbol_present_in_a_merged_chunk() -> None:
    candidate = make_candidate(
        901,
        score=0.3,
        content="def create_user_item():\n    return insert_item()\n",
        symbol_name=None,
        contributing_signals=("lexical", "symbol"),
        raw_signal_scores={"lexical": 0.3, "symbol": 0.2},
        relationship_metadata={"contained_symbols": [
            {"name": "create_user_item", "match_type": "fuzzy"}
        ]},
    )
    evidence = build_evidence([candidate])
    assert classify_evidence_quality(
        evidence, "How does `create_user_item` delegate to `insert_item`?"
    ) is EvidenceQuality.INCOMPLETE
    assert classify_evidence_quality(
        evidence, "How does absent_payment_hook work?"
    ) is EvidenceQuality.NONE


@pytest.mark.parametrize("signal", ["lexical", "symbol"])
def test_evidence_quality_accepts_explicit_nonsemantic_signal(signal: str) -> None:
    evidence = build_evidence(
        [
            make_candidate(
                1,
                score=0.1,
                content="matching",
                signal=signal,
                contributing_signals=(signal,),
                raw_signal_scores={signal: 0.1},
            )
        ]
    )

    assert classify_evidence_quality(evidence) is EvidenceQuality.INCOMPLETE


def test_evidence_quality_accepts_high_semantic_only_match() -> None:
    evidence = build_evidence(
        [
            make_candidate(
                1,
                score=MIN_SEMANTIC_EVIDENCE_SCORE + 0.01,
                content="semantic",
                signal="semantic",
            )
        ]
    )

    assert classify_evidence_quality(evidence) is EvidenceQuality.INCOMPLETE
