import re
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.models import Evidence
from app.models.code_chunk import CodeChunk
from app.models.finding import Finding, FindingType
from app.models.message import Message, MessageRole
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.models.repository_memory import (
    RepositoryMemory,
    RepositoryMemoryConfidence,
    RepositoryMemorySource,
    RepositoryMemoryType,
)
from app.models.session import Session

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
AUTOMATIC_MEMORY_TASKS = {"REPOSITORY_QA", "ARCHITECTURE_EXPLANATION"}
SESSION_MESSAGE_LIMIT = 100


class RepositoryMemoryWriter(Protocol):
    async def save_repository_memory(
        self,
        repository_id: uuid.UUID,
        type: RepositoryMemoryType | str,
        content: str,
        evidence_ids: Sequence[uuid.UUID],
        source: RepositoryMemorySource | str,
        **kwargs: Any,
    ) -> RepositoryMemory: ...


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(value)
        if len(token) >= 3
    }


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _evidence_strings(evidence_ids: Sequence[uuid.UUID]) -> list[str]:
    return [str(item) for item in evidence_ids]


def _durable_source_chunk_ids(evidence: Sequence[Evidence]) -> list[uuid.UUID]:
    durable: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for item in evidence:
        raw_source_ids = item.retrieval_metadata.get("source_chunk_ids") or []
        source_ids = (
            [uuid.UUID(str(value)) for value in raw_source_ids]
            if raw_source_ids
            else [item.evidence_id]
        )
        for source_id in source_ids:
            if source_id not in seen:
                seen.add(source_id)
                durable.append(source_id)
    return durable


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve_session_memory(
        self,
        session_id: uuid.UUID,
        query: str,
    ) -> str:
        recent = list(
            await self._session.scalars(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(SESSION_MESSAGE_LIMIT)
            )
        )
        messages = list(reversed(recent))
        exchanges: list[list[Message]] = []
        current: list[Message] = []
        for message in messages:
            if message.role is MessageRole.USER and current:
                exchanges.append(current)
                current = []
            current.append(message)
        if current:
            exchanges.append(current)

        query_tokens = _tokens(query)
        relevant = [
            exchange
            for exchange in exchanges
            if not query_tokens
            or query_tokens
            & _tokens(" ".join(message.content for message in exchange))
        ][-3:]
        lines: list[str] = []
        for exchange in relevant:
            for message in exchange:
                label = "User" if message.role is MessageRole.USER else "Assistant"
                lines.append(f"{label}: {message.content[:500]}")
        return "\n".join(lines)

    async def retrieve_repository_memory(
        self,
        repository_id: uuid.UUID,
        topic_or_query: str,
        include_stale: bool = False,
    ) -> list[RepositoryMemory]:
        statement = select(RepositoryMemory).where(
            RepositoryMemory.repository_id == repository_id
        )
        if not include_stale:
            statement = statement.where(RepositoryMemory.is_stale.is_(False))
        terms = sorted(_tokens(topic_or_query))
        if terms:
            statement = statement.where(
                or_(
                    *[
                        or_(
                            RepositoryMemory.topic.ilike(f"%{term}%"),
                            RepositoryMemory.content.ilike(f"%{term}%"),
                        )
                        for term in terms
                    ]
                )
            )
        result = await self._session.scalars(
            statement.order_by(
                RepositoryMemory.updated_at.desc(),
                RepositoryMemory.id,
            )
        )
        return list(result)

    async def _latest_index(self, repository_id: uuid.UUID) -> RepositoryIndex:
        index = await self._session.scalar(
            select(RepositoryIndex)
            .where(
                RepositoryIndex.repository_id == repository_id,
                RepositoryIndex.state.in_(
                    [RepositoryIndexState.READY, RepositoryIndexState.PARTIAL]
                ),
            )
            .order_by(RepositoryIndex.version.desc())
            .limit(1)
        )
        if index is None:
            raise ValueError("Repository has no ready index version")
        return index

    async def _validate_evidence_ids(
        self,
        repository_id: uuid.UUID,
        evidence_ids: Sequence[uuid.UUID],
        repository_index_version: int | None = None,
    ) -> int:
        index = await self._latest_index(repository_id)
        if repository_index_version is not None and repository_index_version != index.version:
            raise ValueError("Evidence must belong to the current repository index")
        requested = {uuid.UUID(str(value)) for value in evidence_ids}
        matched = set(
            await self._session.scalars(
                select(CodeChunk.id).where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.repository_index_id == index.id,
                    CodeChunk.id.in_(requested),
                )
            )
        )
        if matched != requested:
            raise ValueError("Evidence IDs must resolve in the current repository index")
        return index.version

    async def save_repository_memory(
        self,
        repository_id: uuid.UUID,
        type: RepositoryMemoryType | str,
        content: str,
        evidence_ids: Sequence[uuid.UUID],
        source: RepositoryMemorySource | str,
        *,
        repository_index_version: int | None = None,
        scope: str = "repository",
        topic: str | None = None,
        confidence: RepositoryMemoryConfidence | str = RepositoryMemoryConfidence.HIGH,
    ) -> RepositoryMemory:
        if not evidence_ids:
            raise ValueError("Repository memory requires at least one evidence_id")
        version = await self._validate_evidence_ids(
            repository_id, evidence_ids, repository_index_version
        )
        item = RepositoryMemory(
            repository_id=repository_id,
            repository_index_version=version,
            type=RepositoryMemoryType(_enum_value(type)),
            scope=scope,
            topic=(topic or content[:255]).strip(),
            content=content,
            evidence_ids=_evidence_strings(evidence_ids),
            confidence=RepositoryMemoryConfidence(_enum_value(confidence)),
            is_stale=False,
            source=RepositoryMemorySource(_enum_value(source)),
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def invalidate_stale(
        self,
        repository_id: uuid.UUID,
        changed_file_paths: Sequence[str],
    ) -> int:
        normalized_paths = {path.replace("\\", "/") for path in changed_file_paths}
        if not normalized_paths:
            return 0
        changed_chunk_ids = {
            str(item)
            for item in await self._session.scalars(
                select(CodeChunk.id).where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.file_path.in_(normalized_paths),
                )
            )
        }
        if not changed_chunk_ids:
            return 0
        memories = list(
            await self._session.scalars(
                select(RepositoryMemory).where(
                    RepositoryMemory.repository_id == repository_id,
                    RepositoryMemory.is_stale.is_(False),
                )
            )
        )
        changed = 0
        for memory in memories:
            if changed_chunk_ids.intersection(memory.evidence_ids):
                memory.is_stale = True
                changed += 1
        await self._session.flush()
        return changed

    async def save_finding(
        self,
        repository_id: uuid.UUID,
        type: FindingType | str,
        content: dict[str, Any] | BaseModel,
        evidence_ids: Sequence[uuid.UUID],
        session_id: uuid.UUID | None,
        *,
        title: str | None = None,
    ) -> Finding:
        if not evidence_ids:
            raise ValueError("A saved finding requires at least one evidence_id")
        await self._validate_evidence_ids(repository_id, evidence_ids)
        if session_id is not None:
            session_repository_id = await self._session.scalar(
                select(Session.repository_id).where(Session.id == session_id)
            )
            if session_repository_id != repository_id:
                raise ValueError("Finding session must belong to the repository")
        finding_type = FindingType(_enum_value(type))
        serialized = (
            content.model_dump(mode="json")
            if isinstance(content, BaseModel)
            else dict(content)
        )
        finding = Finding(
            repository_id=repository_id,
            session_id=session_id,
            type=finding_type,
            title=title or str(serialized.get("title") or finding_type.value),
            content=serialized,
            evidence_ids=_evidence_strings(evidence_ids),
        )
        self._session.add(finding)
        await self._session.flush()
        return finding


async def maybe_write_automatic_repository_memory(
    memory_service: RepositoryMemoryWriter,
    *,
    repository_id: uuid.UUID,
    task_type: Any,
    confidence: Any,
    content: str,
    evidence: Sequence[Evidence],
    memory_type: RepositoryMemoryType | str = RepositoryMemoryType.FACT,
    topic: str | None = None,
    repository_index_version: int | None = None,
) -> RepositoryMemory | None:
    normalized_task = _enum_value(task_type).upper()
    normalized_confidence = _enum_value(confidence).lower()
    code_evidence = [item for item in evidence if item.source_type == "CODE"]
    if (
        normalized_task not in AUTOMATIC_MEMORY_TASKS
        or normalized_confidence != RepositoryMemoryConfidence.HIGH.value
        or not content.strip()
        or not code_evidence
    ):
        return None
    return await memory_service.save_repository_memory(
        repository_id,
        memory_type,
        content,
        _durable_source_chunk_ids(code_evidence),
        RepositoryMemorySource.AUTO,
        repository_index_version=repository_index_version,
        topic=topic or normalized_task.lower(),
        confidence=RepositoryMemoryConfidence.HIGH,
    )
