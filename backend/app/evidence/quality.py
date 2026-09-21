import re
import math

from app.evidence.models import Evidence, EvidenceQuality
from app.retrieval.lexical_search import distinctive_terms

ROUTE_PATTERN = re.compile(
    r"(?:get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
STRONG_SCORE_THRESHOLD = 0.65
# Calibration on mini_fastapi produced an absent email maximum of 0.712626.
# Legitimate lower-scoring paraphrases carry sufficient distinctive lexical
# coverage, so semantic-only evidence must clear this boundary.
MIN_SEMANTIC_EVIDENCE_SCORE = 0.73


def _route_paths(item: Evidence) -> set[str]:
    paths: set[str] = set()
    route_path = item.relationship_metadata.get("route_path")
    if isinstance(route_path, str):
        paths.add(route_path)
    routes = item.relationship_metadata.get("api_routes", [])
    if isinstance(routes, str):
        routes = [routes]
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, str):
                continue
            paths.update(ROUTE_PATTERN.findall(route))
    return paths


def _has_conflict(evidence: list[Evidence]) -> bool:
    symbol_locations: dict[str, set[str]] = {}
    route_locations: dict[str, set[str]] = {}
    for item in evidence:
        if item.symbol and item.file_path:
            symbol_locations.setdefault(item.symbol, set()).add(item.file_path)
        if item.file_path:
            for path in _route_paths(item):
                route_locations.setdefault(path, set()).add(item.file_path)
    return any(len(locations) > 1 for locations in symbol_locations.values()) or any(
        len(locations) > 1 for locations in route_locations.values()
    )


def _signals(item: Evidence) -> set[str]:
    signals = item.retrieval_metadata.get("signals")
    if isinstance(signals, list):
        return {str(signal) for signal in signals}
    signal = item.retrieval_metadata.get("signal")
    return {str(signal)} if signal else set()


def _raw_semantic_score(item: Evidence) -> float:
    raw_scores = item.retrieval_metadata.get("raw_signal_scores")
    if isinstance(raw_scores, dict) and "semantic" in raw_scores:
        return float(raw_scores["semantic"] or 0.0)
    if "semantic" in _signals(item):
        return float(item.retrieval_metadata.get("score", 0.0) or 0.0)
    return 0.0


def _has_exact_symbol_match(evidence: list[Evidence]) -> bool:
    return any(
        contained.get("match_type")
        in {"exact_case_sensitive", "exact_case_insensitive"}
        for item in evidence
        for contained in item.relationship_metadata.get("contained_symbols", [])
    )


def _has_distinctive_lexical_coverage(
    evidence: list[Evidence],
    query: str | None,
) -> bool:
    if not query:
        return any("lexical" in _signals(item) for item in evidence)
    terms = set(distinctive_terms(query))
    if not terms:
        return False
    matched = {
        str(term)
        for item in evidence
        for term in item.relationship_metadata.get("lexical_matched_terms", [])
        if str(term) in terms
    }
    required = 1 if len(terms) == 1 else max(2, math.ceil(len(terms) / 2))
    return len(matched) >= required


def classify_evidence_quality(
    evidence: list[Evidence],
    query: str | None = None,
) -> EvidenceQuality:
    if not evidence:
        return EvidenceQuality.NONE
    has_symbol = _has_exact_symbol_match(evidence) or (
        query is None and any("symbol" in _signals(item) for item in evidence)
    )
    has_lexical_or_symbol = _has_distinctive_lexical_coverage(
        evidence, query
    ) or has_symbol
    max_semantic_score = max(_raw_semantic_score(item) for item in evidence)
    if (
        not has_lexical_or_symbol
        and max_semantic_score < MIN_SEMANTIC_EVIDENCE_SCORE
    ):
        return EvidenceQuality.NONE
    if _has_conflict(evidence):
        return EvidenceQuality.CONFLICTING
    scores = [
        float(item.retrieval_metadata.get("score", 0.0) or 0.0)
        for item in evidence
    ]
    strong_scores = sum(score >= STRONG_SCORE_THRESHOLD for score in scores)
    if len(evidence) >= 3 and strong_scores >= 2:
        return EvidenceQuality.STRONG
    return EvidenceQuality.INCOMPLETE
