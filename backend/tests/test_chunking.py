import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.chunking.base import LARGE_SYMBOL_OVERLAP
from app.chunking.document_chunker import DocumentChunker
from app.chunking.fallback_chunker import FallbackChunker
from app.chunking.js_ts_chunker import JavaScriptTypeScriptChunker
from app.chunking.python_chunker import PythonChunker
from app.db.base import Base
from app.ingestion.chunking_stage import chunk_repository_files
from app.models import (
    CodeChunk,
    CodeChunkType,
    Repository,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.parsing.base import ParsedFile
from app.parsing.fallback import fallback_parsed_file
from app.parsing.javascript_parser import JavaScriptTreeSitterParser
from app.parsing.python_parser import PythonTreeSitterParser


def ids() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_large_function_splits_with_overlap_and_full_symbol_metadata() -> None:
    body = "".join(f"    value_{number} = '{'x' * 90}'\n" for number in range(60))
    source = f"def huge_function():\n{body}    return value_0\n"
    parsed = PythonTreeSitterParser().parse(source, "large.py")
    repository_id, index_id, file_id = ids()

    chunks = PythonChunker().chunk(
        source,
        parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=file_id,
    )
    function_chunks = [
        item for item in chunks if item.chunk_type is CodeChunkType.FUNCTION
    ]

    assert len(function_chunks) >= 2
    assert function_chunks[0].content[-LARGE_SYMBOL_OVERLAP:] == function_chunks[1].content[:LARGE_SYMBOL_OVERLAP]
    for chunk in function_chunks:
        assert chunk.parent_symbol == "huge_function"
        assert chunk.metadata["full_symbol_start_line"] == 1
        assert chunk.metadata["full_symbol_end_line"] == len(source.splitlines())
        assert 1 <= chunk.start_line <= chunk.end_line <= len(source.splitlines())


def test_large_class_keeps_fields_between_methods() -> None:
    large_body = "".join(f"        value_{number} = {number}\n" for number in range(180))
    source = (
        "class Large:\n"
        "    def first(self):\n"
        f"{large_body}"
        "        return value_0\n"
        "    between_methods = 42\n"
        "    def second(self):\n"
        "        return self.between_methods\n"
    )
    parsed = PythonTreeSitterParser().parse(source, "large_class.py")
    repository_id, index_id, file_id = ids()

    chunks = PythonChunker().chunk(
        source,
        parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=file_id,
    )

    assert parsed.parse_ok
    assert any(item.chunk_type is CodeChunkType.METHOD for item in chunks)
    assert any("between_methods = 42" in item.content for item in chunks)


def test_tiny_adjacent_exports_merge_into_module_section() -> None:
    source = (
        "export const first = () => 1;\n"
        "export const second = () => 2;\n"
        "export const third = () => 3;\n"
    )
    parsed = JavaScriptTreeSitterParser().parse(source, "exports.js")
    repository_id, index_id, file_id = ids()

    chunks = JavaScriptTypeScriptChunker().chunk(
        source,
        parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=file_id,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is CodeChunkType.MODULE_SECTION
    assert chunks[0].metadata["merged_symbols"] == ["first", "second", "third"]
    assert len(chunks[0].content) <= 1_500


def test_markdown_document_chunks_on_headings_and_paragraphs() -> None:
    source = "# First\n\nFirst paragraph.\n\n## Second\n\nSecond paragraph.\n"
    parsed = ParsedFile(
        file_path="guide.md",
        language="documentation",
        symbols=[],
        imports=[],
        exports=[],
        parse_ok=True,
        fallback_used=False,
    )
    repository_id, index_id, file_id = ids()

    chunks = DocumentChunker().chunk(
        source,
        parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=file_id,
    )

    assert len(chunks) == 2
    assert all(item.chunk_type is CodeChunkType.DOCUMENTATION for item in chunks)
    assert all(item.source_type == "DOCUMENTATION" for item in chunks)
    assert chunks[0].content.startswith("# First")
    assert chunks[1].content.startswith("## Second")


def test_fallback_file_produces_one_full_file_chunk() -> None:
    source = "def broken(\n"
    parsed = fallback_parsed_file(source, "broken.py", "python")
    repository_id, index_id, file_id = ids()

    chunks = FallbackChunker().chunk(
        source,
        parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=file_id,
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_type is CodeChunkType.FALLBACK
    assert chunks[0].start_line == chunks[0].end_line == 1
    assert chunks[0].content == source


def test_identical_chunk_content_has_identical_hash() -> None:
    repository_id, index_id, first_file_id = ids()
    second_file_id = uuid.uuid4()
    first_parsed = fallback_parsed_file("same content", "first.py", "python")
    second_parsed = fallback_parsed_file("same content", "second.py", "python")

    first = FallbackChunker().chunk(
        "same content",
        first_parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=first_file_id,
    )[0]
    second = FallbackChunker().chunk(
        "same content",
        second_parsed,
        repository_id=repository_id,
        repository_index_id=index_id,
        file_id=second_file_id,
    )[0]

    assert first.file_id != second.file_id
    assert first.content_hash == second.content_hash


@pytest.mark.asyncio
async def test_chunking_stage_persists_one_config_chunk_and_non_null_hashes() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(email="chunks@example.com", hashed_password="unused")
        session.add(user)
        await session.flush()
        repository = Repository(
            owner_id=user.id,
            source_type=RepositorySourceType.UPLOAD,
            name="fixture",
            default_branch="upload",
            selected_branch="upload",
        )
        session.add(repository)
        await session.flush()
        index = RepositoryIndex(
            repository_id=repository.id,
            version=1,
            revision="fixture",
            state=RepositoryIndexState.INDEXING,
        )
        session.add(index)
        await session.flush()
        config = RepositoryFile(
            repository_index_id=index.id,
            path="settings.json",
            language="config",
            content_hash="a" * 64,
            status=RepositoryFileStatus.OK,
            size_bytes=17,
            content='{"enabled": true}',
        )
        pdf = RepositoryFile(
            repository_index_id=index.id,
            path="guide.pdf",
            language=None,
            content_hash=None,
            status=RepositoryFileStatus.BINARY,
            size_bytes=20,
            content="untrusted PDF bytes",
        )
        session.add_all([config, pdf])
        await session.flush()

        drafts = await chunk_repository_files([config, pdf], [])
        rows = list(await session.scalars(select(CodeChunk)))

        assert len(drafts) == len(rows) == 1
        assert rows[0].chunk_type is CodeChunkType.MODULE_SECTION
        assert rows[0].language == "config"
        assert rows[0].content_hash
        assert rows[0].content_hash == drafts[0].content_hash
        assert rows[0].start_line == rows[0].end_line == 1
        assert rows[0].embedding is None
        assert rows[0].chunk_metadata["file_line_count"] == 1

    await engine.dispose()
