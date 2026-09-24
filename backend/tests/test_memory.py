import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.evidence.models import Evidence
from app.evidence.context_builder import ContextBuilder
from app.memory.service import (
    MemoryService,
    maybe_write_automatic_repository_memory,
)
from app.models import (
    CodeChunk,
    CodeChunkType,
    FindingType,
    Message,
    MessageRole,
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositoryMemory,
    RepositoryMemorySource,
    RepositoryMemoryType,
    RepositorySourceType,
    Session,
    User,
)
from app.retrieval.models import RankedChunk


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield factory
    finally:
        await engine.dispose()


async def make_repository(session):
    user = User(email=f"memory-{uuid.uuid4()}@example.com", hashed_password="unused")
    repository = Repository(
        owner=user,
        source_type=RepositorySourceType.UPLOAD,
        name="memory-fixture",
        default_branch="upload",
        selected_branch="upload",
        access_status=RepositoryAccessStatus.ACTIVE,
    )
    session.add(repository)
    await session.flush()
    index = RepositoryIndex(
        repository_id=repository.id,
        version=1,
        revision="memory-fixture",
        state=RepositoryIndexState.READY,
    )
    session.add(index)
    await session.flush()
    return user, repository, index


async def add_chunk(session, repository, index, path: str, content: str):
    repository_file = RepositoryFile(
        repository_index_id=index.id,
        path=path,
        language="python",
        content_hash=uuid.uuid4().hex * 2,
        status=RepositoryFileStatus.OK,
        size_bytes=len(content),
        content=content,
    )
    session.add(repository_file)
    await session.flush()
    chunk = CodeChunk(
        repository_id=repository.id,
        repository_index_id=index.id,
        file_id=repository_file.id,
        file_path=path,
        language="python",
        chunk_type=CodeChunkType.FUNCTION,
        symbol_name="fixture",
        symbol_type="FUNCTION",
        parent_symbol=None,
        start_line=1,
        end_line=1,
        content=content,
        content_hash=uuid.uuid4().hex * 2,
        embedding=None,
        chunk_metadata={"source_type": "CODE"},
    )
    session.add(chunk)
    await session.flush()
    return chunk


@pytest.mark.asyncio
async def test_repository_memory_stale_filter_is_default(session_factory) -> None:
    async with session_factory() as session:
        _, repository, index = await make_repository(session)
        chunk = await add_chunk(session, repository, index, "auth.py", "auth")
        service = MemoryService(session)
        current = await service.save_repository_memory(
            repository.id,
            RepositoryMemoryType.FACT,
            "JWT authentication is used",
            [chunk.id],
            RepositoryMemorySource.EXPLICIT,
            topic="authentication",
        )
        stale = await service.save_repository_memory(
            repository.id,
            RepositoryMemoryType.FACT,
            "An older authentication fact",
            [chunk.id],
            RepositoryMemorySource.EXPLICIT,
            topic="authentication",
        )
        stale.is_stale = True
        await session.flush()

        default = await service.retrieve_repository_memory(
            repository.id, "authentication"
        )
        including_stale = await service.retrieve_repository_memory(
            repository.id, "authentication", include_stale=True
        )

        assert [item.id for item in default] == [current.id]
        assert {item.id for item in including_stale} == {current.id, stale.id}
        context = ContextBuilder().build(
            "authentication",
            "REPOSITORY_QA",
            default,
            [],
            [],
        )
        assert context.repository_memory[0].evidence_ids == [chunk.id]
        assert context.repository_memory[0].source == "EXPLICIT"


@pytest.mark.asyncio
async def test_invalidate_stale_only_marks_changed_file_memories(
    session_factory,
) -> None:
    async with session_factory() as session:
        _, repository, index = await make_repository(session)
        changed_chunk = await add_chunk(
            session, repository, index, "changed.py", "changed"
        )
        stable_chunk = await add_chunk(
            session, repository, index, "stable.py", "stable"
        )
        service = MemoryService(session)
        changed_memory = await service.save_repository_memory(
            repository.id,
            "FACT",
            "Changed fact",
            [changed_chunk.id],
            "EXPLICIT",
            topic="changed",
        )
        stable_memory = await service.save_repository_memory(
            repository.id,
            "FACT",
            "Stable fact",
            [stable_chunk.id],
            "EXPLICIT",
            topic="stable",
        )

        invalidated = await service.invalidate_stale(
            repository.id, ["changed.py"]
        )

        assert invalidated == 1
        assert changed_memory.is_stale is True
        assert stable_memory.is_stale is False


@pytest.mark.asyncio
async def test_merged_evidence_saves_durable_chunks_and_stales_on_file_change(
    session_factory,
) -> None:
    async with session_factory() as session:
        _, repository, index = await make_repository(session)
        first = await add_chunk(session, repository, index, "auth.py", "first auth step")
        second = CodeChunk(
            repository_id=repository.id,
            repository_index_id=index.id,
            file_id=first.file_id,
            file_path="auth.py",
            language="python",
            chunk_type=CodeChunkType.FUNCTION,
            symbol_name="second",
            symbol_type="FUNCTION",
            start_line=2,
            end_line=2,
            content="second auth step",
            content_hash=uuid.uuid4().hex * 2,
            embedding=None,
            chunk_metadata={"source_type": "CODE"},
        )
        session.add(second)
        await session.flush()
        context = ContextBuilder().build(
            "auth",
            "REPOSITORY_QA",
            [],
            [
                RankedChunk(chunk=first, raw_score=0.9, signal="semantic"),
                RankedChunk(chunk=second, raw_score=0.8, signal="semantic"),
            ],
            [],
        )
        assert len(context.evidence) == 1
        merged = context.evidence[0]
        assert merged.evidence_id not in {first.id, second.id}
        assert set(merged.retrieval_metadata["source_chunk_ids"]) == {
            str(first.id), str(second.id)
        }

        memory = await maybe_write_automatic_repository_memory(
            MemoryService(session),
            repository_id=repository.id,
            task_type="REPOSITORY_QA",
            confidence="high",
            content="Authentication follows two steps.",
            evidence=context.evidence,
        )
        assert memory is not None
        assert set(memory.evidence_ids) == {str(first.id), str(second.id)}
        assert await MemoryService(session).invalidate_stale(repository.id, ["auth.py"]) == 1
        assert memory.is_stale is True


@pytest.mark.asyncio
async def test_memory_and_finding_reject_foreign_or_stale_evidence_ids(session_factory) -> None:
    async with session_factory() as session:
        _, repository, index = await make_repository(session)
        other_user, other_repository, other_index = await make_repository(session)
        valid = await add_chunk(session, repository, index, "valid.py", "valid")
        foreign = await add_chunk(session, other_repository, other_index, "foreign.py", "foreign")
        service = MemoryService(session)

        valid_finding = await service.save_finding(
            repository.id, FindingType.IMPACT, {"title": "Valid"}, [valid.id], None
        )
        assert valid_finding.evidence_ids == [str(valid.id)]
        foreign_session = Session(user_id=other_user.id, repository_id=other_repository.id)
        session.add(foreign_session)
        await session.flush()
        with pytest.raises(ValueError, match="session must belong"):
            await service.save_finding(
                repository.id, FindingType.IMPACT, {"title": "Wrong session"},
                [valid.id], foreign_session.id,
            )

        for invalid_id in (uuid.uuid4(), foreign.id):
            with pytest.raises(ValueError, match="current repository index"):
                await service.save_repository_memory(
                    repository.id, "FACT", "Invalid provenance", [invalid_id], "EXPLICIT"
                )
            with pytest.raises(ValueError, match="current repository index"):
                await service.save_finding(
                    repository.id, FindingType.IMPACT, {"title": "Invalid"}, [invalid_id], None
                )
        with pytest.raises(ValueError, match="current repository index"):
            await service.save_repository_memory(
                repository.id,
                "FACT",
                "Old version",
                [valid.id],
                "EXPLICIT",
                repository_index_version=index.version + 1,
            )
        next_index = RepositoryIndex(
            repository_id=repository.id,
            version=index.version + 1,
            revision="new-version",
            state=RepositoryIndexState.READY,
        )
        session.add(next_index)
        await session.flush()
        with pytest.raises(ValueError, match="current repository index"):
            await service.save_repository_memory(
                repository.id, "FACT", "Old evidence", [valid.id], "EXPLICIT"
            )


@pytest.mark.asyncio
async def test_save_finding_rejects_zero_evidence_ids(session_factory) -> None:
    async with session_factory() as session:
        _, repository, _ = await make_repository(session)
        service = MemoryService(session)

        with pytest.raises(ValueError, match="at least one evidence_id"):
            await service.save_finding(
                repository.id,
                FindingType.IMPACT,
                {"title": "Impact"},
                [],
                None,
            )


class RecordingMemoryService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def save_repository_memory(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return object()


def evidence(source_type: str = "CODE") -> Evidence:
    chunk_id = uuid.uuid4()
    return Evidence(
        evidence_id=chunk_id,
        repository_id=uuid.uuid4(),
        repository_index_id=uuid.uuid4(),
        source_type=source_type,
        file_path="auth.py" if source_type == "CODE" else None,
        symbol="login" if source_type == "CODE" else None,
        start_line=1 if source_type == "CODE" else None,
        end_line=5 if source_type == "CODE" else None,
        content_excerpt="evidence",
        relationship_metadata={},
        retrieval_metadata={"score": 0.9, "signal": "hybrid"},
        external_source_metadata=None,
    )


@pytest.mark.asyncio
async def test_automatic_write_only_fires_for_high_confidence_code_evidence() -> None:
    writer = RecordingMemoryService()
    repository_id = uuid.uuid4()

    written = await maybe_write_automatic_repository_memory(
        writer,
        repository_id=repository_id,
        task_type="REPOSITORY_QA",
        confidence="high",
        content="Authentication uses JWT.",
        evidence=[evidence("CODE")],
        repository_index_version=1,
    )
    low = await maybe_write_automatic_repository_memory(
        writer,
        repository_id=repository_id,
        task_type="REPOSITORY_QA",
        confidence="low",
        content="Low confidence",
        evidence=[evidence("CODE")],
    )
    web_only = await maybe_write_automatic_repository_memory(
        writer,
        repository_id=repository_id,
        task_type="ARCHITECTURE_EXPLANATION",
        confidence="high",
        content="External claim",
        evidence=[evidence("WEB")],
    )
    wrong_task = await maybe_write_automatic_repository_memory(
        writer,
        repository_id=repository_id,
        task_type="FLOW_TRACE",
        confidence="high",
        content="Flow fact",
        evidence=[evidence("CODE")],
    )

    assert written is not None
    assert low is web_only is wrong_task is None
    assert len(writer.calls) == 1
    assert writer.calls[0]["args"][4] is RepositoryMemorySource.AUTO
    assert writer.calls[0]["args"][3]


@pytest.mark.asyncio
async def test_session_memory_returns_last_three_relevant_exchanges(
    session_factory,
) -> None:
    async with session_factory() as session:
        user, repository, _ = await make_repository(session)
        conversation = Session(user_id=user.id, repository_id=repository.id)
        session.add(conversation)
        await session.flush()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for number in range(4):
            session.add_all(
                [
                    Message(
                        session_id=conversation.id,
                        role=MessageRole.USER,
                        content=f"Authentication question {number}",
                        created_at=start + timedelta(minutes=number * 2),
                    ),
                    Message(
                        session_id=conversation.id,
                        role=MessageRole.ASSISTANT,
                        content=f"Authentication answer {number}",
                        created_at=start + timedelta(minutes=number * 2 + 1),
                    ),
                ]
            )
        await session.flush()

        summary = await MemoryService(session).retrieve_session_memory(
            conversation.id, "authentication"
        )

        assert "question 0" not in summary
        assert "question 1" in summary
        assert "question 2" in summary
        assert "question 3" in summary


@pytest.mark.asyncio
async def test_session_memory_bounds_the_database_message_query(session_factory) -> None:
    async with session_factory() as session:
        user, repository, _ = await make_repository(session)
        conversation = Session(user_id=user.id, repository_id=repository.id)
        session.add(conversation)
        await session.flush()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for number in range(60):
            session.add_all(
                [
                    Message(
                        session_id=conversation.id,
                        role=MessageRole.USER,
                        content=f"Authentication question {number}",
                        created_at=start + timedelta(minutes=number * 2),
                    ),
                    Message(
                        session_id=conversation.id,
                        role=MessageRole.ASSISTANT,
                        content=f"Authentication answer {number}",
                        created_at=start + timedelta(minutes=number * 2 + 1),
                    ),
                ]
            )
        await session.flush()
        statements: list[str] = []

        def record_message_select(conn, cursor, statement, parameters, context, executemany):
            del conn, cursor, parameters, context, executemany
            if "from messages" in statement.lower():
                statements.append(statement.lower())

        event.listen(session.bind.sync_engine, "before_cursor_execute", record_message_select)
        try:
            summary = await MemoryService(session).retrieve_session_memory(
                conversation.id, "authentication"
            )
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", record_message_select)

        assert statements and all(" limit " in statement for statement in statements)
        assert "question 56" not in summary
        assert all(f"question {number}" in summary for number in (57, 58, 59))
