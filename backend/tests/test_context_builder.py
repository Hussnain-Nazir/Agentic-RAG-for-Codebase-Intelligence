import hashlib
import uuid

from app.evidence.context_builder import MAX_CONTEXT_TOKENS, ContextBuilder
from app.evidence.models import (
    ContextTask,
    EvidenceContext,
    EvidenceQuality,
    RepositoryMemoryContextItem,
    WebEvidenceItem,
)
from app.models import CodeChunk, CodeChunkType
from app.retrieval.models import RankedChunk


def make_candidate(
    number: int,
    *,
    score: float,
    content: str,
    file_path: str | None = None,
    symbol_name: str | None = None,
    metadata: dict | None = None,
    signal: str = "hybrid",
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
        raw_signal_scores={"semantic": score},
        contributing_signals=("semantic",),
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
    for candidate in candidates[:12]:
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
