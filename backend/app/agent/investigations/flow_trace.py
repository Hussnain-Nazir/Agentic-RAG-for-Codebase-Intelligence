import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agent.classification import extract_explicit_symbols
from app.evidence.models import Evidence
from app.schemas.responses import FlowStep, FlowTraceResponse
from app.tools.schemas import (
    FindReferencesInput,
    FindSymbolInput,
    RelatedFilesInput,
)

ToolExecutor = Callable[[str, BaseModel], Awaitable[BaseModel]]


@dataclass(slots=True)
class FlowObservation:
    source_file: str | None
    source_symbol: str
    target_symbol: str | None
    start_line: int | None
    end_line: int | None
    relationship: str | None
    confidence: str | None
    resolved: bool
    evidence_ids: list[uuid.UUID] = field(default_factory=list)

    def as_metadata(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "source_symbol": self.source_symbol,
            "target_symbol": self.target_symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "relationship": self.relationship,
            "confidence": self.confidence,
            "resolved": self.resolved,
            "evidence_ids": [str(item) for item in self.evidence_ids],
        }


@dataclass(slots=True)
class FlowInvestigationState:
    evidence: list[Evidence] = field(default_factory=list)
    observations: list[FlowObservation] = field(default_factory=list)
    visited_symbols: set[str] = field(default_factory=set)

    def add_evidence(self, items: list[Evidence]) -> None:
        existing = {item.evidence_id for item in self.evidence}
        self.evidence.extend(item for item in items if item.evidence_id not in existing)


def _matching_evidence(
    evidence: list[Evidence],
    *,
    file_path: str | None = None,
    symbol: str | None = None,
) -> list[uuid.UUID]:
    matches = [
        item.evidence_id
        for item in evidence
        if (file_path is None or item.file_path == file_path)
        and (
            symbol is None
            or item.symbol == symbol
            or symbol in item.content_excerpt
        )
    ]
    return list(dict.fromkeys(matches))


async def investigate_flow_trace(
    task: str,
    repository_id: uuid.UUID,
    execute_tool: ToolExecutor,
    state: FlowInvestigationState,
) -> FlowInvestigationState:
    queue = list(extract_explicit_symbols(task))
    while queue:
        symbol_name = queue.pop(0)
        if symbol_name in state.visited_symbols:
            continue
        state.visited_symbols.add(symbol_name)

        definitions = await execute_tool(
            "find_symbol",
            FindSymbolInput(
                repository_id=repository_id,
                symbol_name=symbol_name,
            ),
        )
        definition_rows = [
            item
            for item in getattr(definitions, "root", [])
            if item.name == symbol_name
            or item.name.lower() == symbol_name.lower()
        ]
        if not definition_rows:
            evidence_ids = _matching_evidence(
                state.evidence,
                symbol=symbol_name,
            )
            evidence = next(
                (
                    item
                    for item in state.evidence
                    if item.evidence_id in evidence_ids
                ),
                None,
            )
            state.observations.append(
                FlowObservation(
                    source_file=evidence.file_path if evidence else None,
                    source_symbol=symbol_name,
                    target_symbol=None,
                    start_line=evidence.start_line if evidence else None,
                    end_line=evidence.end_line if evidence else None,
                    relationship=None,
                    confidence=None,
                    resolved=False,
                    evidence_ids=evidence_ids,
                )
            )
            continue

        references = await execute_tool(
            "find_references",
            FindReferencesInput(
                repository_id=repository_id,
                symbol_name=symbol_name,
            ),
        )
        related = await execute_tool(
            "get_related_files",
            RelatedFilesInput(
                repository_id=repository_id,
                symbol_name_or_chunk_id=symbol_name,
            ),
        )
        state.add_evidence(list(getattr(related, "root", [])))

        for reference in getattr(references, "root", []):
            evidence_ids = _matching_evidence(
                state.evidence,
                file_path=reference.file,
                symbol=reference.symbol,
            )
            supporting_evidence = next(
                (
                    item
                    for item in state.evidence
                    if item.evidence_id in evidence_ids
                ),
                None,
            )
            state.observations.append(
                FlowObservation(
                    source_file=reference.file,
                    source_symbol=reference.symbol,
                    target_symbol=symbol_name,
                    start_line=(
                        supporting_evidence.start_line
                        if supporting_evidence
                        else reference.line
                    ),
                    end_line=(
                        supporting_evidence.end_line
                        if supporting_evidence
                        else reference.line
                    ),
                    relationship=reference.relationship_kind,
                    confidence=reference.confidence,
                    resolved=bool(evidence_ids),
                    evidence_ids=evidence_ids,
                )
            )
            if reference.symbol not in state.visited_symbols:
                queue.append(reference.symbol)

    return state


def partial_flow_trace(
    state: FlowInvestigationState,
    evidence: list[Evidence],
) -> FlowTraceResponse:
    steps: list[FlowStep] = []
    for observation in state.observations:
        if (
            observation.source_file is None
            or observation.start_line is None
            or observation.end_line is None
            or not observation.evidence_ids
        ):
            continue
        steps.append(
            FlowStep(
                order=len(steps) + 1,
                file=observation.source_file,
                symbol=observation.source_symbol,
                start_line=observation.start_line,
                end_line=observation.end_line,
                explanation=(
                    f"Observed {observation.source_symbol} referencing "
                    f"{observation.target_symbol}."
                    if observation.resolved
                    else f"Could not resolve the next transition from {observation.source_symbol}."
                ),
                relationship_to_next=(
                    observation.relationship if observation.resolved else None
                ),
                unresolved=not observation.resolved,
                evidence_ids=observation.evidence_ids,
            )
        )
    return FlowTraceResponse(
        summary="The bounded investigation returned a partial flow trace.",
        steps=steps,
        evidence=evidence,
    )


def enforce_observed_transitions(
    response: FlowTraceResponse,
    state: FlowInvestigationState,
) -> FlowTraceResponse:
    data = response.model_dump()
    resolved_observations = [
        observation for observation in state.observations if observation.resolved
    ]
    for index, step in enumerate(data["steps"]):
        if step["unresolved"] or step["relationship_to_next"] is None:
            continue
        next_step = data["steps"][index + 1] if index + 1 < len(data["steps"]) else None
        backed = next_step is not None and any(
            observation.source_file == step["file"]
            and observation.source_symbol == step["symbol"]
            and observation.target_symbol == next_step["symbol"]
            and observation.relationship == step["relationship_to_next"]
            for observation in resolved_observations
        )
        if not backed:
            step["unresolved"] = True
            step["relationship_to_next"] = None
    return FlowTraceResponse.model_validate(data)
