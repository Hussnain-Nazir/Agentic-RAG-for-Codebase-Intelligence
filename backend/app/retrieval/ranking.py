import hashlib
import re
import uuid
from collections.abc import Iterable

from app.models.code_chunk import CodeChunk
from app.retrieval.models import ContainedSymbol, RankedChunk

SIGNAL_WEIGHTS = {
    "semantic": 0.5,
    "lexical": 0.3,
}
SYMBOL_PRESENCE_WEIGHT = 0.2
EXACT_SYMBOL_BOOST = 0.5
QUERY_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SIGNAL_ORDER = {
    "hybrid": 0,
    "semantic": 1,
    "lexical": 2,
    "symbol": 3,
    "structural": 4,
}


def _source_ids(candidate: RankedChunk) -> tuple[uuid.UUID, ...]:
    return candidate.source_chunk_ids or (candidate.chunk.id,)


def _sort_key(candidate: RankedChunk) -> tuple[float, int, str, int, int, str]:
    return (
        -candidate.raw_score,
        SIGNAL_ORDER[candidate.signal],
        candidate.chunk.file_path,
        candidate.chunk.start_line,
        candidate.chunk.end_line,
        str(candidate.chunk.id),
    )


def normalize_scores(candidates: list[RankedChunk]) -> list[RankedChunk]:
    """Min-max normalize raw scores independently for each signal."""
    if not candidates:
        return []
    bounds: dict[str, tuple[float, float]] = {}
    for candidate in candidates:
        current = bounds.get(candidate.signal)
        if current is None:
            bounds[candidate.signal] = (candidate.raw_score, candidate.raw_score)
        else:
            bounds[candidate.signal] = (
                min(current[0], candidate.raw_score),
                max(current[1], candidate.raw_score),
            )

    normalized: list[RankedChunk] = []
    for candidate in candidates:
        minimum, maximum = bounds[candidate.signal]
        score = (
            1.0
            if maximum == minimum
            else (candidate.raw_score - minimum) / (maximum - minimum)
        )
        normalized.append(
            RankedChunk(
                chunk=candidate.chunk,
                raw_score=score,
                signal=candidate.signal,
                source_chunk_ids=_source_ids(candidate),
                final_score=score,
                raw_signal_scores=dict(candidate.raw_signal_scores),
                contributing_signals=candidate.contributing_signals,
                contained_symbols=candidate.contained_symbols,
                relationship_metadata=dict(candidate.relationship_metadata),
            )
        )
    return normalized


def _query_has_symbol(query_text: str, symbol_name: str) -> bool:
    tokens = QUERY_TOKEN_PATTERN.findall(query_text)
    if symbol_name in tokens:
        return True
    lowered = symbol_name.lower()
    return any(token.lower() == lowered for token in tokens)


def _has_exact_symbol_match(candidate: RankedChunk, query_text: str) -> bool:
    if candidate.chunk.symbol_name and _query_has_symbol(
        query_text, candidate.chunk.symbol_name
    ):
        return True
    return any(
        symbol.match_type in {
            "exact_case_sensitive",
            "exact_case_insensitive",
        }
        and _query_has_symbol(query_text, symbol.name)
        for symbol in candidate.contained_symbols
    )


def merge_candidates(
    semantic: list[RankedChunk],
    lexical: list[RankedChunk],
    symbol: list[RankedChunk],
    query_text: str,
) -> list[RankedChunk]:
    """Normalize and merge the three retrieval signals with frozen weights."""
    normalized = normalize_scores([*semantic, *lexical, *symbol])
    chunks: dict[uuid.UUID, CodeChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    symbol_chunks: set[uuid.UUID] = set()
    source_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    raw_scores: dict[uuid.UUID, dict[str, float]] = {}
    contributing: dict[uuid.UUID, set[str]] = {}
    contained_symbols: dict[uuid.UUID, set[ContainedSymbol]] = {}
    relationships: dict[uuid.UUID, dict[str, object]] = {}

    for candidate in [*semantic, *lexical, *symbol]:
        chunk_id = candidate.chunk.id
        raw_scores.setdefault(chunk_id, {})[candidate.signal] = max(
            candidate.raw_score,
            raw_scores.get(chunk_id, {}).get(candidate.signal, float("-inf")),
        )
        contributing.setdefault(chunk_id, set()).add(candidate.signal)
        contained_symbols.setdefault(chunk_id, set()).update(
            candidate.contained_symbols
        )
        relationships.setdefault(chunk_id, {}).update(
            candidate.relationship_metadata
        )

    for candidate in normalized:
        chunk_id = candidate.chunk.id
        chunks[chunk_id] = candidate.chunk
        source_ids.setdefault(chunk_id, set()).update(_source_ids(candidate))
        if candidate.signal == "symbol":
            symbol_chunks.add(chunk_id)
            continue
        scores[chunk_id] = scores.get(chunk_id, 0.0) + (
            SIGNAL_WEIGHTS[candidate.signal] * candidate.raw_score
        )

    merged: list[RankedChunk] = []
    for chunk_id, chunk in chunks.items():
        score = scores.get(chunk_id, 0.0)
        if chunk_id in symbol_chunks:
            score += SYMBOL_PRESENCE_WEIGHT
        symbol_metadata = tuple(
            sorted(
                contained_symbols[chunk_id],
                key=lambda item: (
                    item.file_path,
                    item.start_line,
                    item.end_line,
                    item.name,
                    item.match_type,
                ),
            )
        )
        boost_candidate = RankedChunk(
            chunk=chunk,
            raw_score=score,
            signal="hybrid",
            contained_symbols=symbol_metadata,
        )
        if _has_exact_symbol_match(boost_candidate, query_text):
            score += EXACT_SYMBOL_BOOST
        merged.append(
            RankedChunk(
                chunk=chunk,
                raw_score=score,
                signal="hybrid",
                source_chunk_ids=tuple(sorted(source_ids[chunk_id], key=str)),
                final_score=score,
                raw_signal_scores=raw_scores[chunk_id],
                contributing_signals=tuple(
                    signal
                    for signal in ("semantic", "lexical", "symbol")
                    if signal in contributing[chunk_id]
                ),
                contained_symbols=symbol_metadata,
                relationship_metadata=relationships[chunk_id],
            )
        )
    return sorted(merged, key=_sort_key)


def _overlap_ratio(left: CodeChunk, right: CodeChunk) -> float:
    overlap = max(
        0,
        min(left.end_line, right.end_line) - max(left.start_line, right.start_line) + 1,
    )
    shorter = min(
        left.end_line - left.start_line + 1,
        right.end_line - right.start_line + 1,
    )
    return overlap / shorter if shorter > 0 else 0.0


def deduplicate_by_chunk_and_overlap(
    candidates: list[RankedChunk],
) -> list[RankedChunk]:
    """Keep the highest-scored duplicate or greater-than-50-percent overlap."""
    ordered = sorted(candidates, key=_sort_key)
    surviving: list[RankedChunk] = []
    seen_ids: set[uuid.UUID] = set()
    for candidate in ordered:
        if candidate.chunk.id in seen_ids:
            continue
        if any(
            existing.chunk.file_path == candidate.chunk.file_path
            and _overlap_ratio(existing.chunk, candidate.chunk) > 0.5
            for existing in surviving
        ):
            continue
        surviving.append(candidate)
        seen_ids.add(candidate.chunk.id)
    return sorted(surviving, key=_sort_key)


def _merged_chunk(group: list[RankedChunk]) -> RankedChunk:
    if len(group) == 1:
        return group[0]
    by_position = sorted(
        group,
        key=lambda item: (
            item.chunk.start_line,
            item.chunk.end_line,
            str(item.chunk.id),
        ),
    )
    best = min(group, key=_sort_key)
    source_ids = sorted(
        {source_id for item in group for source_id in _source_ids(item)},
        key=str,
    )
    content = "\n".join(item.chunk.content for item in by_position)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    merged_id = uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(item) for item in source_ids))
    chunk = CodeChunk(
        id=merged_id,
        repository_id=best.chunk.repository_id,
        repository_index_id=best.chunk.repository_index_id,
        file_id=best.chunk.file_id,
        file_path=best.chunk.file_path,
        language=best.chunk.language,
        chunk_type=best.chunk.chunk_type,
        symbol_name=best.chunk.symbol_name,
        symbol_type=best.chunk.symbol_type,
        parent_symbol=best.chunk.parent_symbol,
        start_line=min(item.chunk.start_line for item in group),
        end_line=max(item.chunk.end_line for item in group),
        content=content,
        content_hash=digest,
        embedding=None,
        embedding_model_version=best.chunk.embedding_model_version,
        chunk_metadata={
            **best.chunk.chunk_metadata,
            "merged_adjacent": True,
            "source_chunk_ids": [str(item) for item in source_ids],
        },
    )
    merged_raw_scores: dict[str, float] = {}
    merged_signals: set[str] = set()
    merged_symbols: set[ContainedSymbol] = set()
    merged_relationships: dict[str, object] = {}
    for item in group:
        merged_signals.update(item.contributing_signals)
        merged_symbols.update(item.contained_symbols)
        if item.chunk.symbol_name:
            merged_symbols.add(ContainedSymbol(
                name=item.chunk.symbol_name,
                file_path=item.chunk.file_path,
                start_line=item.chunk.start_line,
                end_line=item.chunk.end_line,
                match_type="contained",
            ))
        merged_relationships.update(item.relationship_metadata)
        for signal, score in item.raw_signal_scores.items():
            merged_raw_scores[signal] = max(
                score,
                merged_raw_scores.get(signal, float("-inf")),
            )
    return RankedChunk(
        chunk=chunk,
        raw_score=max(item.raw_score for item in group),
        signal=best.signal,
        source_chunk_ids=tuple(source_ids),
        final_score=max(item.raw_score for item in group),
        raw_signal_scores=merged_raw_scores,
        contributing_signals=tuple(
            signal
            for signal in ("semantic", "lexical", "symbol", "hybrid", "structural")
            if signal in merged_signals
        ),
        contained_symbols=tuple(
            sorted(
                merged_symbols,
                key=lambda item: (
                    item.file_path,
                    item.start_line,
                    item.end_line,
                    item.name,
                    item.match_type,
                ),
            )
        ),
        relationship_metadata=merged_relationships,
    )


def merge_adjacent_chunks(candidates: list[RankedChunk]) -> list[RankedChunk]:
    """Merge same-file chunks separated by at most five lines."""
    by_file: dict[tuple[uuid.UUID, str], list[RankedChunk]] = {}
    for candidate in candidates:
        key = (candidate.chunk.repository_index_id, candidate.chunk.file_path)
        by_file.setdefault(key, []).append(candidate)

    merged: list[RankedChunk] = []
    for key in sorted(by_file, key=lambda item: (str(item[0]), item[1])):
        positioned = sorted(
            by_file[key],
            key=lambda item: (
                item.chunk.start_line,
                item.chunk.end_line,
                str(item.chunk.id),
            ),
        )
        group: list[RankedChunk] = []
        group_end = -1
        for candidate in positioned:
            if group and candidate.chunk.start_line - group_end > 5:
                merged.append(_merged_chunk(group))
                group = []
                group_end = -1
            group.append(candidate)
            group_end = max(group_end, candidate.chunk.end_line)
        if group:
            merged.append(_merged_chunk(group))
    return sorted(merged, key=_sort_key)


def sort_ranked(candidates: Iterable[RankedChunk]) -> list[RankedChunk]:
    return sorted(candidates, key=_sort_key)
