import uuid
from typing import Any, Literal

from pydantic import BaseModel

from app.evidence.models import Evidence

Confidence = Literal["high", "medium", "low"]


class RepositoryAnswer(BaseModel):
    answer: str
    evidence: list[Evidence]
    confidence: Confidence
    limitations: str | None


class FlowStep(BaseModel):
    order: int
    file: str
    symbol: str
    start_line: int
    end_line: int
    explanation: str
    relationship_to_next: str | None
    unresolved: bool
    evidence_ids: list[uuid.UUID]


class FlowTraceResponse(BaseModel):
    summary: str
    steps: list[FlowStep]
    evidence: list[Evidence]


class ImpactItem(BaseModel):
    file: str
    symbol: str
    reason: str
    confidence: Confidence
    evidence_ids: list[uuid.UUID]
    recommended_action: str
    tests_to_inspect: list[str]


class ChangeImpactResponse(BaseModel):
    requested_change: str
    directly_affected: list[ImpactItem]
    likely_indirectly_affected: list[ImpactItem]
    evidence: list[Evidence]


class ArchitectureResponse(BaseModel):
    languages: list[str]
    main_folders: list[str]
    frameworks_detected: list[str]
    entrypoints: list[str]
    backend_boundary: str | None
    frontend_boundary: str | None
    database_layer: str | None
    api_organization: str | None
    auth_locations: list[str]
    test_locations: list[str]
    evidence: list[Evidence]


class ModelResult(BaseModel):
    slot: Literal["A", "B"]
    model_name: str
    response: Any
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    validation_status: str
    error: str | None


class ModelComparisonResponse(BaseModel):
    question: str
    evidence_context_id: uuid.UUID
    results: list[ModelResult]
