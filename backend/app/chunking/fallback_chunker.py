import uuid

from app.chunking.base import ChunkDraft, make_draft
from app.models.code_chunk import CodeChunkType
from app.parsing.base import ParsedFile


class FallbackChunker:
    def chunk(
        self,
        source: str,
        parsed_file: ParsedFile,
        *,
        repository_id: uuid.UUID,
        repository_index_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> list[ChunkDraft]:
        line_count = max(len(source.splitlines()), 1)
        return [
            make_draft(
                repository_id=repository_id,
                repository_index_id=repository_index_id,
                file_id=file_id,
                file_path=parsed_file.file_path,
                language=parsed_file.language,
                chunk_type=CodeChunkType.FALLBACK,
                start_line=1,
                end_line=line_count,
                content=source,
                metadata={
                    **parsed_file.metadata,
                    "source_type": "CODE",
                },
            )
        ]
