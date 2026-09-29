import math
import re
import uuid
from typing import Any

from app.evidence.builder import MAX_EVIDENCE_EXCERPT_CHARS, build_evidence
from app.evidence.models import (
    ContextTask,
    Evidence,
    EvidenceContext,
    RepositoryMemoryContextItem,
    WebEvidenceItem,
)
from app.evidence.quality import classify_evidence_quality
from app.retrieval.models import RankedChunk
from app.retrieval.ranking import (
    deduplicate_by_chunk_and_overlap,
    merge_adjacent_chunks,
)

MAX_CONTEXT_TOKENS = 8_000
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * 4
MAX_EVIDENCE_ITEMS = 16
KEYWORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _keyword_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if value is None:
        return []
    try:
        return [item for item in value if isinstance(item, str)]
    except TypeError:
        return []


def _task_model(task: Any) -> ContextTask:
    if isinstance(task, ContextTask):
        return task
    if isinstance(task, str):
        return ContextTask(query=task, extracted_keywords=[])
    if isinstance(task, dict):
        query = str(task.get("query") or task.get("question") or "")
        keywords = task.get("extracted_keywords") or task.get("keywords") or []
        return ContextTask(query=query, extracted_keywords=_keyword_list(keywords))
    query = str(getattr(task, "query", getattr(task, "question", task)))
    keywords = getattr(
        task,
        "extracted_keywords",
        getattr(task, "keywords", []),
    )
    return ContextTask(query=query, extracted_keywords=_keyword_list(keywords))


def _task_type_value(task_type: Any) -> str:
    value = getattr(task_type, "value", task_type)
    return str(value)


def _keywords(task: ContextTask, task_type: str) -> set[str]:
    values = [task.query, task_type, *task.extracted_keywords]
    return {
        token.lower()
        for value in values
        for token in KEYWORD_PATTERN.findall(value)
        if len(token) >= 3
    }


def _memory_model(item: Any) -> RepositoryMemoryContextItem:
    if isinstance(item, RepositoryMemoryContextItem):
        return item
    if isinstance(item, dict):
        return RepositoryMemoryContextItem.model_validate(item)
    return RepositoryMemoryContextItem(
        id=getattr(item, "id", None),
        repository_id=getattr(item, "repository_id", None),
        repository_index_version=getattr(item, "repository_index_version", None),
        scope=getattr(item, "scope", None),
        topic=str(getattr(item, "topic", "")),
        content=str(getattr(item, "content", "")),
        tags=list(getattr(item, "tags", []) or []),
        evidence_ids=[
            uuid.UUID(str(value))
            for value in (getattr(item, "evidence_ids", []) or [])
        ],
        confidence=(
            str(getattr(getattr(item, "confidence", None), "value", getattr(item, "confidence", None)))
            if getattr(item, "confidence", None) is not None
            else None
        ),
        source=(
            str(getattr(getattr(item, "source", None), "value", getattr(item, "source", None)))
            if getattr(item, "source", None) is not None
            else None
        ),
        is_stale=bool(getattr(item, "is_stale", False)),
    )


def _filter_memory(
    repository_memory: list[Any],
    keywords: set[str],
) -> list[RepositoryMemoryContextItem]:
    selected: list[RepositoryMemoryContextItem] = []
    for raw_item in repository_memory:
        item = _memory_model(raw_item)
        if item.is_stale:
            continue
        searchable = " ".join([item.topic, *item.tags]).lower()
        if keywords and not any(keyword in searchable for keyword in keywords):
            continue
        selected.append(item)
    return selected


def _web_evidence(
    items: list[WebEvidenceItem] | None,
    repository_id: uuid.UUID | None,
    repository_index_id: uuid.UUID | None,
) -> list[Evidence]:
    if not items:
        return []
    evidence: list[Evidence] = []
    for item in items:
        evidence.append(
            Evidence(
                evidence_id=uuid.uuid5(uuid.NAMESPACE_URL, f"prism:web:{item.url}"),
                repository_id=item.repository_id or repository_id or uuid.UUID(int=0),
                repository_index_id=(
                    item.repository_index_id
                    or repository_index_id
                    or uuid.UUID(int=0)
                ),
                source_type="WEB",
                file_path=None,
                symbol=None,
                start_line=None,
                end_line=None,
                content_excerpt=item.snippet[:MAX_EVIDENCE_EXCERPT_CHARS],
                relationship_metadata={},
                retrieval_metadata={"score": item.score, "signal": "web"},
                external_source_metadata={
                    "title": item.title,
                    "url": item.url,
                    "source_domain": item.source_domain,
                    "retrieved_at": (
                        item.retrieved_at.isoformat() if item.retrieved_at else None
                    ),
                },
            )
        )
    return evidence


def _evidence_sort_key(item: Evidence) -> tuple[int, float, str, int, str]:
    is_expansion = bool(
        item.retrieval_metadata.get("is_structural_expansion", False)
    )
    source_priority = 2 if is_expansion else 1 if item.source_type == "WEB" else 0
    score = float(item.retrieval_metadata.get("score", 0.0) or 0.0)
    return (
        source_priority,
        -score,
        item.file_path or "",
        item.start_line or 0,
        str(item.evidence_id),
    )


def _dedupe_evidence(evidence: list[Evidence], *, preserve_order: bool = False) -> list[Evidence]:
    seen: set[tuple[Any, ...]] = set()
    result: list[Evidence] = []
    for item in evidence if preserve_order else sorted(evidence, key=_evidence_sort_key):
        if item.source_type == "WEB":
            key = ("WEB", (item.external_source_metadata or {}).get("url"))
        else:
            key = (
                item.repository_id,
                item.repository_index_id,
                item.file_path,
                item.start_line,
                item.end_line,
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


class ContextBuilder:
    def build_from_evidence(
        self,
        task: Any,
        task_type: Any,
        repository_memory: list[Any],
        repository_evidence: list[Evidence],
        web_evidence: list[WebEvidenceItem] | None = None,
        *,
        preserve_order: bool = False,
    ) -> EvidenceContext:
        task_model = _task_model(task)
        task_type_value = _task_type_value(task_type)
        relevant_memory = _filter_memory(
            repository_memory,
            _keywords(task_model, task_type_value),
        )
        repository_id = (
            repository_evidence[0].repository_id if repository_evidence else None
        )
        repository_index_id = (
            repository_evidence[0].repository_index_id
            if repository_evidence
            else None
        )
        combined = _dedupe_evidence(
            [
                *repository_evidence,
                *_web_evidence(web_evidence, repository_id, repository_index_id),
            ],
            preserve_order=preserve_order,
        )
        kept: list[Evidence] = []
        used_chars = 0
        for item in combined[:MAX_EVIDENCE_ITEMS]:
            item_chars = len(item.content_excerpt)
            if used_chars + item_chars > MAX_CONTEXT_CHARS:
                break
            kept.append(item)
            used_chars += item_chars
        kept_memory: list[RepositoryMemoryContextItem] = []
        for item in relevant_memory:
            if used_chars + len(item.content) > MAX_CONTEXT_CHARS:
                break
            kept_memory.append(item)
            used_chars += len(item.content)
        file_line_counts: dict[str, int] = {}
        for item in kept:
            if item.file_path and item.end_line is not None:
                stored_count = int(
                    item.retrieval_metadata.get("file_line_count", item.end_line)
                )
                file_line_counts[item.file_path] = max(
                    stored_count,
                    file_line_counts.get(item.file_path, 0),
                )
        context_seed = "|".join(
            [
                task_model.query,
                task_type_value,
                *(str(item.evidence_id) for item in kept),
            ]
        )
        return EvidenceContext(
            context_id=uuid.uuid5(uuid.NAMESPACE_URL, context_seed),
            repository_id=repository_id,
            repository_index_id=repository_index_id,
            file_line_counts=file_line_counts,
            task=task_model,
            task_type=task_type_value,
            repository_memory=kept_memory,
            evidence=kept,
            quality=classify_evidence_quality(kept, task_model.query),
            estimated_tokens=math.ceil(used_chars / 4),
        )

    def build(
        self,
        task: Any,
        task_type: Any,
        repository_memory: list[Any],
        retrieval_candidates: list[RankedChunk],
        structural_evidence: list[RankedChunk],
        web_evidence: list[WebEvidenceItem] | None = None,
    ) -> EvidenceContext:
        task_model = _task_model(task)
        task_type_value = _task_type_value(task_type)
        relevant_memory = _filter_memory(
            repository_memory,
            _keywords(task_model, task_type_value),
        )

        ranked = deduplicate_by_chunk_and_overlap(
            [*retrieval_candidates, *structural_evidence]
        )
        ranked = merge_adjacent_chunks(ranked)
        repository_id = ranked[0].chunk.repository_id if ranked else None
        repository_index_id = (
            ranked[0].chunk.repository_index_id if ranked else None
        )
        file_line_counts: dict[str, int] = {}
        for candidate in ranked:
            stored_line_count = candidate.chunk.chunk_metadata.get(
                "file_line_count",
                candidate.chunk.end_line,
            )
            file_line_counts[candidate.chunk.file_path] = max(
                int(stored_line_count),
                file_line_counts.get(candidate.chunk.file_path, 0),
            )
        combined = _dedupe_evidence(
            [
                *build_evidence(ranked),
                *_web_evidence(web_evidence, repository_id, repository_index_id),
            ]
        )

        kept: list[Evidence] = []
        used_chars = 0
        for item in combined[:MAX_EVIDENCE_ITEMS]:
            item_chars = len(item.content_excerpt)
            if used_chars + item_chars > MAX_CONTEXT_CHARS:
                break
            kept.append(item)
            used_chars += item_chars

        kept_memory: list[RepositoryMemoryContextItem] = []
        for item in relevant_memory:
            if used_chars + len(item.content) > MAX_CONTEXT_CHARS:
                break
            kept_memory.append(item)
            used_chars += len(item.content)

        context_seed = "|".join(
            [
                task_model.query,
                task_type_value,
                *(str(item.evidence_id) for item in kept),
            ]
        )
        quality = classify_evidence_quality(kept, task_model.query)
        return EvidenceContext(
            context_id=uuid.uuid5(uuid.NAMESPACE_URL, context_seed),
            repository_id=repository_id,
            repository_index_id=repository_index_id,
            file_line_counts=file_line_counts,
            task=task_model,
            task_type=task_type_value,
            repository_memory=kept_memory,
            evidence=kept,
            quality=quality,
            estimated_tokens=math.ceil(used_chars / 4),
        )
