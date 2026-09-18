import uuid

from app.chunking._structural import chunk_structural_file
from app.chunking.base import ChunkDraft
from app.parsing.base import ParsedFile


class JavaScriptTypeScriptChunker:
    def chunk(
        self,
        source: str,
        parsed_file: ParsedFile,
        *,
        repository_id: uuid.UUID,
        repository_index_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> list[ChunkDraft]:
        return chunk_structural_file(
            source,
            parsed_file,
            repository_id=repository_id,
            repository_index_id=repository_index_id,
            file_id=file_id,
        )
