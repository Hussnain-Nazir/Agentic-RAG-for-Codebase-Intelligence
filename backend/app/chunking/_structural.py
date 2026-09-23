import uuid

from app.chunking.base import (
    LARGE_SYMBOL_CHARS,
    MODULE_SECTION_CHARS,
    ChunkDraft,
    leading_comment_start,
    make_draft,
    merge_tiny_adjacent,
    source_slice,
    split_large_chunk,
    symbol_chunk_type,
)
from app.models.code_chunk import CodeChunkType
from app.parsing.base import ParsedFile


def chunk_structural_file(
    source: str,
    parsed_file: ParsedFile,
    *,
    repository_id: uuid.UUID,
    repository_index_id: uuid.UUID,
    file_id: uuid.UUID,
) -> list[ChunkDraft]:
    lines = source.splitlines(keepends=True)
    if not lines:
        lines = [""]
    symbol_chunks: list[ChunkDraft] = []
    occupied: set[int] = set()
    methods_by_parent = {
        symbol.name: [
            candidate
            for candidate in parsed_file.symbols
            if candidate.symbol_type == "METHOD" and candidate.parent_symbol == symbol.name
        ]
        for symbol in parsed_file.symbols
        if symbol.symbol_type == "CLASS"
    }

    for symbol in sorted(parsed_file.symbols, key=lambda item: (item.start_line, item.end_line)):
        if symbol.symbol_type == "METHOD":
            continue
        start_line = leading_comment_start(lines, symbol.start_line, parsed_file.language)
        end_line = min(symbol.end_line, len(lines))
        content = source_slice(lines, start_line, end_line)
        class_methods = sorted(
            methods_by_parent.get(symbol.name, []),
            key=lambda item: (item.start_line, item.end_line),
        )
        if (
            symbol.symbol_type == "CLASS"
            and len(content) > LARGE_SYMBOL_CHARS
            and class_methods
        ):
            header_end = min(class_methods[0].start_line - 1, end_line)
            if header_end >= start_line:
                header_content = source_slice(lines, start_line, header_end)
                if header_content.strip():
                    symbol_chunks.append(
                        make_draft(
                            repository_id=repository_id,
                            repository_index_id=repository_index_id,
                            file_id=file_id,
                            file_path=parsed_file.file_path,
                            language=parsed_file.language,
                            chunk_type=CodeChunkType.CLASS,
                            symbol_name=symbol.name,
                            symbol_type=symbol.symbol_type,
                            parent_symbol=symbol.parent_symbol,
                            start_line=start_line,
                            end_line=header_end,
                            content=header_content,
                            metadata={
                                **symbol.metadata,
                                "original_start_line": symbol.start_line,
                                "original_end_line": symbol.end_line,
                                "large_class_split_by_method": True,
                                "source_type": "CODE",
                            },
                        )
                    )
                    occupied.update(range(start_line, header_end + 1))
            for method in class_methods:
                method_start = leading_comment_start(
                    lines,
                    method.start_line,
                    parsed_file.language,
                )
                method_content = source_slice(lines, method_start, method.end_line)
                method_draft = make_draft(
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file_id,
                    file_path=parsed_file.file_path,
                    language=parsed_file.language,
                    chunk_type=CodeChunkType.METHOD,
                    symbol_name=method.name,
                    symbol_type=method.symbol_type,
                    parent_symbol=symbol.name,
                    start_line=method_start,
                    end_line=method.end_line,
                    content=method_content,
                    metadata={
                        **method.metadata,
                        "original_start_line": method.start_line,
                        "original_end_line": method.end_line,
                        "parent_class": symbol.name,
                        "source_type": "CODE",
                    },
                )
                symbol_chunks.extend(split_large_chunk(method_draft))
                occupied.update(range(method_start, method.end_line + 1))
            continue
        draft = make_draft(
            repository_id=repository_id,
            repository_index_id=repository_index_id,
            file_id=file_id,
            file_path=parsed_file.file_path,
            language=parsed_file.language,
            chunk_type=symbol_chunk_type(symbol),
            symbol_name=symbol.name,
            symbol_type=symbol.symbol_type,
            parent_symbol=symbol.parent_symbol,
            start_line=start_line,
            end_line=end_line,
            content=content,
            metadata={
                **symbol.metadata,
                "original_start_line": symbol.start_line,
                "original_end_line": symbol.end_line,
                "source_type": "CODE",
            },
        )
        symbol_chunks.extend(split_large_chunk(draft))
        occupied.update(range(start_line, end_line + 1))

    symbol_chunks = merge_tiny_adjacent(symbol_chunks, lines)

    module_line_groups: list[tuple[int, int]] = []
    group_start: int | None = None
    for line_number in range(1, len(lines) + 1):
        if line_number not in occupied:
            if group_start is None:
                group_start = line_number
        elif group_start is not None:
            module_line_groups.append((group_start, line_number - 1))
            group_start = None
    if group_start is not None:
        module_line_groups.append((group_start, len(lines)))

    module_chunks: list[ChunkDraft] = []
    for start_line, end_line in module_line_groups:
        if not source_slice(lines, start_line, end_line).strip():
            continue
        cursor = start_line
        while cursor <= end_line:
            single_line = source_slice(lines, cursor, cursor)
            if len(single_line) > MODULE_SECTION_CHARS:
                for offset in range(0, len(single_line), MODULE_SECTION_CHARS):
                    content = single_line[offset : offset + MODULE_SECTION_CHARS]
                    module_chunks.append(
                        make_draft(
                            repository_id=repository_id,
                            repository_index_id=repository_index_id,
                            file_id=file_id,
                            file_path=parsed_file.file_path,
                            language=parsed_file.language,
                            chunk_type=CodeChunkType.MODULE_SECTION,
                            start_line=cursor,
                            end_line=cursor,
                            content=content,
                            metadata={"source_type": "CODE"},
                        )
                    )
                cursor += 1
                continue
            part_end = cursor
            while part_end <= end_line:
                candidate = source_slice(lines, cursor, part_end)
                if len(candidate) > MODULE_SECTION_CHARS and part_end > cursor:
                    part_end -= 1
                    break
                if len(candidate) > MODULE_SECTION_CHARS:
                    break
                part_end += 1
            if part_end > end_line:
                part_end = end_line
            content = source_slice(lines, cursor, part_end)
            module_chunks.append(
                make_draft(
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file_id,
                    file_path=parsed_file.file_path,
                    language=parsed_file.language,
                    chunk_type=CodeChunkType.MODULE_SECTION,
                    start_line=cursor,
                    end_line=part_end,
                    content=content,
                    metadata={"source_type": "CODE"},
                )
            )
            cursor = part_end + 1

    return sorted(
        [*module_chunks, *symbol_chunks],
        key=lambda item: (item.start_line, item.end_line, item.chunk_type.value),
    )
