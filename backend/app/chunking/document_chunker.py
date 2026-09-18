import re
import uuid
from dataclasses import dataclass

from app.chunking.base import MODULE_SECTION_CHARS, ChunkDraft, make_draft
from app.models.code_chunk import CodeChunkType
from app.parsing.base import ParsedFile


@dataclass(frozen=True, slots=True)
class _Block:
    start_line: int
    end_line: int
    content: str
    starts_with_heading: bool


def _blocks(source: str) -> list[_Block]:
    lines = source.splitlines(keepends=True)
    if not lines:
        return [_Block(1, 1, "", False)]
    blocks: list[_Block] = []
    start = 1
    current: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        is_heading = bool(re.match(r"^#{1,6}\s+", line))
        if is_heading and current:
            content = "".join(current)
            blocks.append(
                _Block(start, line_number - 1, content, content.lstrip().startswith("#"))
            )
            current = []
        if not current:
            start = line_number
        current.append(line)
        if not line.strip():
            content = "".join(current)
            blocks.append(
                _Block(start, line_number, content, content.lstrip().startswith("#"))
            )
            current = []
    if current:
        content = "".join(current)
        blocks.append(_Block(start, len(lines), content, content.lstrip().startswith("#")))
    return [block for block in blocks if block.content.strip()]


class DocumentChunker:
    def chunk(
        self,
        source: str,
        parsed_file: ParsedFile,
        *,
        repository_id: uuid.UUID,
        repository_index_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> list[ChunkDraft]:
        chunks: list[ChunkDraft] = []
        pending: list[_Block] = []

        def flush() -> None:
            nonlocal pending
            if not pending:
                return
            content = "".join(block.content for block in pending)
            chunks.append(
                make_draft(
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file_id,
                    file_path=parsed_file.file_path,
                    language="documentation",
                    chunk_type=CodeChunkType.DOCUMENTATION,
                    start_line=pending[0].start_line,
                    end_line=pending[-1].end_line,
                    content=content,
                    metadata={"source_type": "DOCUMENTATION"},
                    source_type="DOCUMENTATION",
                )
            )
            pending = []

        for block in _blocks(source):
            if block.starts_with_heading and pending:
                flush()
            if len(block.content) > MODULE_SECTION_CHARS:
                flush()
                for offset in range(0, len(block.content), MODULE_SECTION_CHARS):
                    content = block.content[offset : offset + MODULE_SECTION_CHARS]
                    start_line = block.start_line + block.content[:offset].count("\n")
                    end_line = start_line + max(content.count("\n"), 0)
                    if content.endswith("\n") and end_line > start_line:
                        end_line -= 1
                    chunks.append(
                        make_draft(
                            repository_id=repository_id,
                            repository_index_id=repository_index_id,
                            file_id=file_id,
                            file_path=parsed_file.file_path,
                            language="documentation",
                            chunk_type=CodeChunkType.DOCUMENTATION,
                            start_line=start_line,
                            end_line=end_line,
                            content=content,
                            metadata={"source_type": "DOCUMENTATION"},
                            source_type="DOCUMENTATION",
                        )
                    )
                continue
            candidate = "".join(item.content for item in [*pending, block])
            if pending and len(candidate) > MODULE_SECTION_CHARS:
                flush()
            pending.append(block)
        flush()
        return chunks
