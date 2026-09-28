import hashlib
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from app.models.code_chunk import CodeChunkType
from app.parsing.base import ExtractedSymbol, ParsedFile

LARGE_SYMBOL_CHARS = 4_000
LARGE_SYMBOL_OVERLAP = 200
MODULE_SECTION_CHARS = 1_500
TINY_SYMBOL_CHARS = 300


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    repository_id: uuid.UUID
    repository_index_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    language: str
    chunk_type: CodeChunkType
    symbol_name: str | None
    symbol_type: str | None
    parent_symbol: str | None
    start_line: int
    end_line: int
    content: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = "CODE"


class Chunker(Protocol):
    def chunk(
        self,
        source: str,
        parsed_file: ParsedFile,
        *,
        repository_id: uuid.UUID,
        repository_index_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> list[ChunkDraft]: ...


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_draft(
    *,
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    file_id: uuid.UUID,
    file_path: str,
    language: str,
    chunk_type: CodeChunkType,
    start_line: int,
    end_line: int,
    content: str,
    symbol_name: str | None = None,
    symbol_type: str | None = None,
    parent_symbol: str | None = None,
    metadata: dict[str, Any] | None = None,
    source_type: str = "CODE",
) -> ChunkDraft:
    return ChunkDraft(
        repository_id=repository_id,
        repository_index_id=repository_index_id,
        file_id=file_id,
        file_path=file_path,
        language=language,
        chunk_type=chunk_type,
        symbol_name=symbol_name,
        symbol_type=symbol_type,
        parent_symbol=parent_symbol,
        start_line=start_line,
        end_line=end_line,
        content=content,
        content_hash=content_hash(content),
        metadata=dict(metadata or {}),
        source_type=source_type,
    )


def _line_for_offset(content: str, base_line: int, offset: int, *, end: bool) -> int:
    line = base_line + content[:offset].count("\n")
    if end and offset > 0 and content[offset - 1] == "\n":
        line -= 1
    return max(line, base_line)


def split_large_chunk(draft: ChunkDraft) -> list[ChunkDraft]:
    if len(draft.content) <= LARGE_SYMBOL_CHARS:
        return [draft]
    step = LARGE_SYMBOL_CHARS - LARGE_SYMBOL_OVERLAP
    pieces: list[ChunkDraft] = []
    offsets = list(range(0, len(draft.content), step))
    for index, start in enumerate(offsets):
        end = min(start + LARGE_SYMBOL_CHARS, len(draft.content))
        segment = draft.content[start:end]
        metadata = {
            **draft.metadata,
            "full_symbol_start_line": draft.start_line,
            "full_symbol_end_line": draft.end_line,
            "segment_index": index,
            "segment_count": len(offsets),
            "parent_symbol": draft.parent_symbol or draft.symbol_name,
        }
        pieces.append(
            replace(
                draft,
                parent_symbol=draft.parent_symbol or draft.symbol_name,
                start_line=_line_for_offset(draft.content, draft.start_line, start, end=False),
                end_line=_line_for_offset(draft.content, draft.start_line, end, end=True),
                content=segment,
                content_hash=content_hash(segment),
                metadata=metadata,
            )
        )
        if end == len(draft.content):
            break
    return pieces


def symbol_chunk_type(symbol: ExtractedSymbol) -> CodeChunkType:
    try:
        return CodeChunkType(symbol.symbol_type)
    except ValueError:
        return CodeChunkType.MODULE_SECTION


def source_slice(lines: list[str], start_line: int, end_line: int) -> str:
    return "".join(lines[start_line - 1 : end_line])


def leading_comment_start(lines: list[str], start_line: int, language: str) -> int:
    index = start_line - 2
    earliest = start_line
    in_block_comment = False
    while index >= 0:
        stripped = lines[index].strip()
        if language == "python":
            is_comment = stripped.startswith("#")
        else:
            if stripped.endswith("*/"):
                in_block_comment = True
            is_comment = stripped.startswith("//") or stripped.startswith("/*") or in_block_comment
            if stripped.startswith("/*"):
                in_block_comment = False
        if not stripped or is_comment:
            earliest = index + 1
            index -= 1
            continue
        break
    return earliest


def merge_tiny_adjacent(chunks: list[ChunkDraft], source_lines: list[str]) -> list[ChunkDraft]:
    ordered = sorted(chunks, key=lambda item: (item.start_line, item.end_line))
    merged: list[ChunkDraft] = []
    pending: list[ChunkDraft] = []

    def flush() -> None:
        nonlocal pending
        if len(pending) < 2:
            merged.extend(pending)
            pending = []
            return
        start_line = pending[0].start_line
        end_line = pending[-1].end_line
        content = source_slice(source_lines, start_line, end_line)
        first = pending[0]
        merged.append(
            make_draft(
                repository_id=first.repository_id,
                repository_index_id=first.repository_index_id,
                file_id=first.file_id,
                file_path=first.file_path,
                language=first.language,
                chunk_type=CodeChunkType.MODULE_SECTION,
                start_line=start_line,
                end_line=end_line,
                content=content,
                metadata={
                    "merged_symbols": [item.symbol_name for item in pending],
                    "contained_symbol_calls": [
                        {
                            "name": item.symbol_name,
                            "start_line": item.metadata.get("original_start_line", item.start_line),
                            "calls": list(item.metadata.get("calls", [])),
                            "direct_calls": list(item.metadata.get("direct_calls", [])),
                        }
                        for item in pending
                        if item.symbol_name
                    ],
                    "source_type": first.source_type,
                },
                source_type=first.source_type,
            )
        )
        pending = []

    for chunk in ordered:
        can_merge = (
            len(chunk.content) <= TINY_SYMBOL_CHARS
            and (
                not pending
                or chunk.start_line <= pending[-1].end_line + 2
            )
        )
        if can_merge:
            candidate_start = pending[0].start_line if pending else chunk.start_line
            candidate_content = source_slice(source_lines, candidate_start, chunk.end_line)
            if len(candidate_content) <= MODULE_SECTION_CHARS:
                pending.append(chunk)
                continue
        flush()
        if len(chunk.content) <= TINY_SYMBOL_CHARS:
            pending = [chunk]
        else:
            merged.append(chunk)
    flush()
    return sorted(merged, key=lambda item: (item.start_line, item.end_line))
