from pathlib import PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_object_session

from app.chunking.base import ChunkDraft, make_draft
from app.chunking.document_chunker import DocumentChunker
from app.chunking.fallback_chunker import FallbackChunker
from app.chunking.js_ts_chunker import JavaScriptTypeScriptChunker
from app.chunking.python_chunker import PythonChunker
from app.models.code_chunk import CodeChunk, CodeChunkType
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_index import RepositoryIndex
from app.parsing.base import ParsedFile

CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml"}
DOCUMENT_EXTENSIONS = {".md", ".txt"}


def _plain_parsed(file: RepositoryFile, language: str) -> ParsedFile:
    return ParsedFile(
        file_path=file.path,
        language=language,
        symbols=[],
        imports=[],
        exports=[],
        parse_ok=True,
        fallback_used=False,
        metadata={},
    )


async def chunk_repository_files(
    files: list[RepositoryFile],
    parsed_files: list[ParsedFile],
) -> list[ChunkDraft]:
    if not files:
        return []
    session = async_object_session(files[0])
    if session is None:
        raise ValueError("Repository files must be attached to an AsyncSession")
    index_ids = {item.repository_index_id for item in files}
    if len(index_ids) != 1:
        raise ValueError("Repository files must belong to one index version")
    repository_index_id = next(iter(index_ids))
    repository_id = await session.scalar(
        select(RepositoryIndex.repository_id).where(
            RepositoryIndex.id == repository_index_id
        )
    )
    if repository_id is None:
        raise ValueError("Repository index does not exist")

    await session.execute(
        delete(CodeChunk).where(CodeChunk.repository_index_id == repository_index_id)
    )
    parsed_by_path = {item.file_path: item for item in parsed_files}
    files_by_id = {item.id: item for item in files}
    drafts: list[ChunkDraft] = []

    for file in files:
        if file.status is not RepositoryFileStatus.OK or file.content is None:
            continue
        suffix = PurePosixPath(file.path).suffix.lower()
        parsed = parsed_by_path.get(file.path)
        if suffix in CONFIG_EXTENSIONS:
            line_count = max(len(file.content.splitlines()), 1)
            drafts.append(
                make_draft(
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file.id,
                    file_path=file.path,
                    language="config",
                    chunk_type=CodeChunkType.MODULE_SECTION,
                    start_line=1,
                    end_line=line_count,
                    content=file.content,
                    metadata={"source_type": "CODE"},
                )
            )
        elif suffix in DOCUMENT_EXTENSIONS:
            drafts.extend(
                DocumentChunker().chunk(
                    file.content,
                    _plain_parsed(file, "documentation"),
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file.id,
                )
            )
        elif parsed is not None and not parsed.parse_ok:
            drafts.extend(
                FallbackChunker().chunk(
                    file.content,
                    parsed,
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file.id,
                )
            )
        elif parsed is not None:
            chunker = (
                PythonChunker()
                if parsed.language == "python"
                else JavaScriptTypeScriptChunker()
            )
            drafts.extend(
                chunker.chunk(
                    file.content,
                    parsed,
                    repository_id=repository_id,
                    repository_index_id=repository_index_id,
                    file_id=file.id,
                )
            )

    for draft in drafts:
        source_file = files_by_id[draft.file_id]
        file_line_count = max(len((source_file.content or "").splitlines()), 1)
        session.add(
            CodeChunk(
                repository_id=draft.repository_id,
                repository_index_id=draft.repository_index_id,
                file_id=draft.file_id,
                file_path=draft.file_path,
                language=draft.language,
                chunk_type=draft.chunk_type,
                symbol_name=draft.symbol_name,
                symbol_type=draft.symbol_type,
                parent_symbol=draft.parent_symbol,
                start_line=draft.start_line,
                end_line=draft.end_line,
                content=draft.content,
                content_hash=draft.content_hash,
                embedding=None,
                chunk_metadata={
                    **draft.metadata,
                    "source_type": draft.source_type,
                    "file_line_count": file_line_count,
                },
            )
        )
    await session.flush()
    return drafts
