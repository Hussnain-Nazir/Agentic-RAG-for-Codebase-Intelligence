from typing import Any

from app.evidence.models import Evidence
from app.retrieval.models import RankedChunk

MAX_EVIDENCE_EXCERPT_CHARS = 4_000


def _source_type(candidate: RankedChunk) -> str:
    value = candidate.chunk.chunk_metadata.get("source_type", "CODE")
    return value if value in {"CODE", "DOCUMENTATION"} else "CODE"


def _relationship_metadata(candidate: RankedChunk) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(candidate.relationship_metadata)
    stored = candidate.chunk.chunk_metadata.get("relationship_metadata")
    if isinstance(stored, dict):
        metadata.update(stored)
    for key in ("api_routes", "route_path", "relationship_kind"):
        if key in candidate.chunk.chunk_metadata:
            metadata[key] = candidate.chunk.chunk_metadata[key]
    if candidate.chunk.parent_symbol:
        metadata["parent_symbol"] = candidate.chunk.parent_symbol
    if candidate.contained_symbols:
        metadata["contained_symbols"] = [
            {
                "name": item.name,
                "file_path": item.file_path,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "match_type": item.match_type,
            }
            for item in candidate.contained_symbols
        ]
    return metadata


def _evidence_symbol(candidate: RankedChunk) -> str | None:
    if candidate.chunk.symbol_name:
        return candidate.chunk.symbol_name
    exact = next(
        (
            item.name
            for item in candidate.contained_symbols
            if item.match_type
            in {"exact_case_sensitive", "exact_case_insensitive"}
        ),
        None,
    )
    return exact


def build_evidence(ranked_chunks: list[RankedChunk]) -> list[Evidence]:
    """Build real, version-scoped Evidence objects from ranked chunks."""
    evidence: list[Evidence] = []
    for candidate in ranked_chunks:
        chunk = candidate.chunk
        evidence.append(
            Evidence(
                evidence_id=chunk.id,
                repository_id=chunk.repository_id,
                repository_index_id=chunk.repository_index_id,
                source_type=_source_type(candidate),
                file_path=chunk.file_path,
                symbol=_evidence_symbol(candidate),
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content_excerpt=chunk.content[:MAX_EVIDENCE_EXCERPT_CHARS],
                relationship_metadata=_relationship_metadata(candidate),
                retrieval_metadata={
                    "score": candidate.final_score,
                    "signal": candidate.signal,
                    "signals": list(candidate.contributing_signals),
                    "raw_signal_scores": dict(candidate.raw_signal_scores),
                    "source_chunk_ids": [
                        str(item) for item in candidate.source_chunk_ids
                    ],
                    "is_structural_expansion": candidate.signal == "structural",
                    "file_line_count": candidate.chunk.chunk_metadata.get(
                        "file_line_count",
                        candidate.chunk.end_line,
                    ),
                },
                external_source_metadata=None,
            )
        )
    return evidence
