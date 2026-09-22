import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agent.classification import extract_explicit_symbols
from app.agent.investigations.flow_trace import select_entry_symbol
from app.evidence.models import Evidence
from app.schemas.responses import ChangeImpactResponse, ImpactItem
from app.tools.schemas import (
    FindReferencesInput,
    FindSymbolInput,
    RelatedFilesInput,
    RepositoryQueryInput,
)

ToolExecutor = Callable[[str, BaseModel], Awaitable[BaseModel]]


@dataclass(slots=True)
class ImpactCandidate:
    file: str
    symbol: str
    reason: str
    evidence_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass(slots=True)
class ChangeImpactState:
    target_symbol: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    directly_affected: dict[tuple[str, str], ImpactCandidate] = field(default_factory=dict)
    likely_indirectly_affected: dict[tuple[str, str], ImpactCandidate] = field(
        default_factory=dict
    )

    def add_evidence(self, items: list[Evidence]) -> None:
        seen = {item.evidence_id for item in self.evidence}
        for item in items:
            if item.evidence_id not in seen:
                self.evidence.append(item)
                seen.add(item.evidence_id)

    def as_metadata(
        self, available_ids: set[uuid.UUID] | None = None
    ) -> dict[str, object]:
        def items(values: dict[tuple[str, str], ImpactCandidate]) -> list[dict]:
            return [
                {
                    "file": item.file,
                    "symbol": item.symbol,
                    "reason": item.reason,
                    "evidence_ids": [
                        str(value) for value in item.evidence_ids
                        if available_ids is None or value in available_ids
                    ],
                }
                for item in values.values()
                if available_ids is None
                or any(value in available_ids for value in item.evidence_ids)
            ]

        return {
            "target_symbol": self.target_symbol,
            "directly_affected": items(self.directly_affected),
            "likely_indirectly_affected": items(self.likely_indirectly_affected),
        }


def _supporting(evidence: list[Evidence], file: str, symbol: str) -> list[uuid.UUID]:
    return [
        item.evidence_id
        for item in evidence
        if item.file_path == file
        and (
            item.symbol == symbol
            or symbol in item.content_excerpt
            or any(
                contained.get("name") == symbol
                for contained in item.relationship_metadata.get("contained_symbols", [])
            )
        )
    ]


async def investigate_change_impact(
    task: str,
    repository_id: uuid.UUID,
    execute_tool: ToolExecutor,
    state: ChangeImpactState,
) -> ChangeImpactState:
    candidates = extract_explicit_symbols(task)
    inferred = select_entry_symbol(task, state.evidence)
    if inferred and inferred not in candidates:
        candidates.append(inferred)
    for candidate in candidates[:2]:
        result = await execute_tool(
            "find_symbol",
            FindSymbolInput(repository_id=repository_id, symbol_name=candidate),
        )
        definitions = [
            item for item in getattr(result, "root", [])
            if item.name.lower() == candidate.lower()
        ]
        if not definitions:
            continue
        state.target_symbol = definitions[0].name
        references = await execute_tool(
            "find_references",
            FindReferencesInput(
                repository_id=repository_id, symbol_name=state.target_symbol
            ),
        )
        related = await execute_tool(
            "get_related_files",
            RelatedFilesInput(
                repository_id=repository_id,
                symbol_name_or_chunk_id=state.target_symbol,
                include_seed=True,
            ),
        )
        state.add_evidence(list(getattr(related, "root", [])))
        targeted = await execute_tool(
            "search_codebase",
            RepositoryQueryInput(
                repository_id=repository_id,
                query=state.target_symbol,
                top_k=12,
            ),
        )
        state.add_evidence(list(getattr(targeted, "root", [])))
        for definition in definitions:
            ids = _supporting(state.evidence, definition.file_path, definition.name)
            if ids:
                key = (definition.file_path, definition.name)
                state.directly_affected[key] = ImpactCandidate(
                    file=definition.file_path,
                    symbol=definition.name,
                    reason="Defines the symbol named in the requested change.",
                    evidence_ids=ids,
                )
        for reference in getattr(references, "root", []):
            key = (reference.file, reference.symbol)
            if key in state.directly_affected:
                continue
            ids = _supporting(state.evidence, reference.file, reference.symbol)
            if ids:
                state.likely_indirectly_affected[key] = ImpactCandidate(
                    file=reference.file,
                    symbol=reference.symbol,
                    reason=(
                        f"Stored {reference.relationship_kind} relationship references "
                        f"{state.target_symbol}; inspect the consumer for impact."
                    ),
                    evidence_ids=ids,
                )
        for item in state.evidence:
            if (
                item.source_type != "CODE"
                or not item.file_path
                or not item.symbol
                or item.symbol == state.target_symbol
                or state.target_symbol not in item.content_excerpt
            ):
                continue
            path = item.file_path.lower()
            if not (
                "test" in path
                or "schema" in path
                or "types" in path
                or path.startswith("frontend/")
                or path.endswith((".ts", ".tsx", ".js", ".jsx"))
            ):
                continue
            key = (item.file_path, item.symbol)
            if key not in state.directly_affected and key not in state.likely_indirectly_affected:
                state.likely_indirectly_affected[key] = ImpactCandidate(
                    file=item.file_path,
                    symbol=item.symbol,
                    reason=(
                        f"Source evidence in this type, frontend, or test area "
                        f"mentions {state.target_symbol}; inspect for downstream impact."
                    ),
                    evidence_ids=[item.evidence_id],
                )
        break
    return state


def enforce_observed_impacts(
    response: ChangeImpactResponse,
    state: ChangeImpactState,
    evidence: list[Evidence],
) -> ChangeImpactResponse:
    canonical = {item.evidence_id: item for item in evidence}
    data = response.model_dump()
    used_ids: set[uuid.UUID] = set()
    for field_name in ("directly_affected", "likely_indirectly_affected"):
        allowed = getattr(state, field_name)
        valid: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in data[field_name]:
            key = (item["file"], item["symbol"])
            candidate = allowed.get(key)
            if candidate is None or key in seen:
                continue
            valid_ids = [
                value
                for value in item["evidence_ids"]
                if value in canonical
                and value in candidate.evidence_ids
                and canonical[value].file_path == item["file"]
            ]
            if not valid_ids:
                continue
            item["evidence_ids"] = valid_ids
            item["reason"] = candidate.reason
            item["confidence"] = (
                "high" if field_name == "directly_affected" else "medium"
            )
            item["tests_to_inspect"] = (
                [candidate.file] if "test" in candidate.file.lower() else []
            )
            valid.append(item)
            seen.add(key)
            used_ids.update(valid_ids)
        for key, candidate in allowed.items():
            if key in seen:
                continue
            valid_ids = [
                value for value in candidate.evidence_ids
                if value in canonical and canonical[value].file_path == candidate.file
            ]
            if not valid_ids:
                continue
            valid.append(
                ImpactItem(
                    file=candidate.file,
                    symbol=candidate.symbol,
                    reason=candidate.reason,
                    confidence="high" if field_name == "directly_affected" else "medium",
                    evidence_ids=valid_ids,
                    recommended_action="Inspect this area for compatibility with the change.",
                    tests_to_inspect=[candidate.file] if "test" in candidate.file.lower() else [],
                ).model_dump()
            )
            used_ids.update(valid_ids)
        data[field_name] = valid
    data["evidence"] = [
        item.model_dump() for item in evidence if item.evidence_id in used_ids
    ]
    return ChangeImpactResponse.model_validate(data)
