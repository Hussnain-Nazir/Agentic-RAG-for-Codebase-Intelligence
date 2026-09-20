import re

from app.evidence.models import Evidence, EvidenceQuality

ROUTE_PATTERN = re.compile(
    r"(?:get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
STRONG_SCORE_THRESHOLD = 0.65
# Calibration on mini_fastapi produced legitimate maxima >= 0.765312 and
# absent-topic maxima <= 0.617336. This boundary leaves more than 0.07
# cosine-similarity margin on each side.
MIN_SEMANTIC_EVIDENCE_SCORE = 0.69


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


def classify_evidence_quality(evidence: list[Evidence]) -> EvidenceQuality:
    if not evidence:
        return EvidenceQuality.NONE
    has_lexical_or_symbol = any(
        _signals(item).intersection({"lexical", "symbol"}) for item in evidence
    )
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
