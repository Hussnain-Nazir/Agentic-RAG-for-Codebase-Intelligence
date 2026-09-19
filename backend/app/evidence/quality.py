import re

from app.evidence.models import Evidence, EvidenceQuality

ROUTE_PATTERN = re.compile(
    r"(?:get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
STRONG_SCORE_THRESHOLD = 0.65


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


def classify_evidence_quality(evidence: list[Evidence]) -> EvidenceQuality:
    if not evidence:
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
