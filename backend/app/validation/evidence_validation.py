import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.evidence.models import Evidence, EvidenceContext
from app.schemas.responses import (
    ChangeImpactResponse,
    FlowTraceResponse,
    RepositoryAnswer,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class ValidationResult(BaseModel, Generic[ResponseT]):
    response: ResponseT
    downgraded: bool
    removed_citations: list[str]


def _lower_confidence(value: str) -> str:
    return {"high": "medium", "medium": "low", "low": "low"}.get(value, "low")


def _context_index(context: EvidenceContext) -> uuid.UUID | None:
    if context.repository_index_id is not None:
        return context.repository_index_id
    return next(
        (
            item.repository_index_id
            for item in context.evidence
            if item.source_type != "WEB"
        ),
        None,
    )


def _file_counts(context: EvidenceContext) -> dict[str, int]:
    counts = dict(context.file_line_counts)
    for item in context.evidence:
        if item.file_path and item.end_line is not None:
            counts[item.file_path] = max(counts.get(item.file_path, 0), item.end_line)
    return counts


def _citation_valid(
    evidence_id: uuid.UUID,
    *,
    cited_file: str | None,
    cited_start: int | None,
    cited_end: int | None,
    cited_repository_id: uuid.UUID | None,
    cited_repository_index_id: uuid.UUID | None,
    canonical: dict[uuid.UUID, Evidence],
    context: EvidenceContext,
    file_counts: dict[str, int],
) -> bool:
    # 1. The evidence ID must come from the exact context sent to the model.
    original = canonical.get(evidence_id)
    if original is None:
        return False

    # 2. The cited path must exist in the current index representation.
    file_path = cited_file if cited_file is not None else original.file_path
    if original.source_type != "WEB":
        if not file_path or file_path not in file_counts:
            return False
        if original.file_path != file_path:
            return False

    # 3. Line ranges must be real and remain within five lines of the excerpt.
    if original.source_type != "WEB":
        start = cited_start if cited_start is not None else original.start_line
        end = cited_end if cited_end is not None else original.end_line
        if start is None or end is None or start < 1 or end < start:
            return False
        if end > file_counts[file_path]:
            return False
        if original.start_line is None or original.end_line is None:
            return False
        if abs(start - original.start_line) > 5 or abs(end - original.end_line) > 5:
            return False

    # 4. Repository and index provenance must match the current context.
    current_index = _context_index(context)
    if (
        cited_repository_index_id is not None
        and cited_repository_index_id != original.repository_index_id
    ):
        return False
    if cited_repository_id is not None and cited_repository_id != original.repository_id:
        return False
    if current_index is not None and original.repository_index_id != current_index:
        return False
    if context.repository_id is not None and original.repository_id != context.repository_id:
        return False
    return True


def validate_citations(
    response: ResponseT,
    evidence_context: EvidenceContext,
) -> ValidationResult[ResponseT]:
    canonical = {item.evidence_id: item for item in evidence_context.evidence}
    file_counts = _file_counts(evidence_context)
    data = response.model_dump()
    removed: list[str] = []
    kept_ids: set[uuid.UUID] = set()

    for citation in data.get("evidence", []):
        evidence_id = uuid.UUID(str(citation["evidence_id"]))
        if _citation_valid(
            evidence_id,
            cited_file=citation.get("file_path"),
            cited_start=citation.get("start_line"),
            cited_end=citation.get("end_line"),
            cited_repository_id=uuid.UUID(str(citation["repository_id"])),
            cited_repository_index_id=uuid.UUID(
                str(citation["repository_index_id"])
            ),
            canonical=canonical,
            context=evidence_context,
            file_counts=file_counts,
        ):
            kept_ids.add(evidence_id)
        else:
            removed.append(str(evidence_id))

    if isinstance(response, FlowTraceResponse):
        for step in data["steps"]:
            valid_ids: list[uuid.UUID] = []
            for raw_id in step["evidence_ids"]:
                evidence_id = uuid.UUID(str(raw_id))
                if _citation_valid(
                    evidence_id,
                    cited_file=step["file"],
                    cited_start=step["start_line"],
                    cited_end=step["end_line"],
                    cited_repository_id=None,
                    cited_repository_index_id=None,
                    canonical=canonical,
                    context=evidence_context,
                    file_counts=file_counts,
                ):
                    valid_ids.append(evidence_id)
                    kept_ids.add(evidence_id)
                else:
                    removed.append(str(evidence_id))
            if len(valid_ids) != len(step["evidence_ids"]):
                step["unresolved"] = True
            step["evidence_ids"] = valid_ids

    if isinstance(response, ChangeImpactResponse):
        for field in ("directly_affected", "likely_indirectly_affected"):
            for item in data[field]:
                valid_ids: list[uuid.UUID] = []
                for raw_id in item["evidence_ids"]:
                    evidence_id = uuid.UUID(str(raw_id))
                    if _citation_valid(
                        evidence_id,
                        cited_file=item["file"],
                        cited_start=None,
                        cited_end=None,
                        cited_repository_id=None,
                        cited_repository_index_id=None,
                        canonical=canonical,
                        context=evidence_context,
                        file_counts=file_counts,
                    ):
                        valid_ids.append(evidence_id)
                        kept_ids.add(evidence_id)
                    else:
                        removed.append(str(evidence_id))
                if len(valid_ids) != len(item["evidence_ids"]):
                    item["confidence"] = _lower_confidence(item["confidence"])
                item["evidence_ids"] = valid_ids

    if "evidence" in data:
        data["evidence"] = [
            item.model_dump()
            for item in evidence_context.evidence
            if item.evidence_id in kept_ids
        ]

    unique_removed = list(dict.fromkeys(removed))
    if unique_removed and isinstance(response, RepositoryAnswer):
        data["confidence"] = _lower_confidence(data["confidence"])
        limitation = "One or more citations failed evidence validation."
        data["limitations"] = (
            f"{data['limitations']} {limitation}" if data.get("limitations") else limitation
        )

    validated = type(response).model_validate(data)
    return ValidationResult(
        response=validated,
        downgraded=bool(unique_removed),
        removed_citations=unique_removed,
    )
