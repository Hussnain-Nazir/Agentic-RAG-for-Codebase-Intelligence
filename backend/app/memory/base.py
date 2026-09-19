import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from app.models.finding import Finding
from app.models.repository_memory import RepositoryMemory


class MemoryServiceProtocol(Protocol):
    async def retrieve_session_memory(
        self, session_id: uuid.UUID, query: str
    ) -> str: ...

    async def retrieve_repository_memory(
        self,
        repository_id: uuid.UUID,
        topic_or_query: str,
        include_stale: bool = False,
    ) -> list[RepositoryMemory]: ...

    async def save_repository_memory(
        self,
        repository_id: uuid.UUID,
        type: Any,
        content: str,
        evidence_ids: Sequence[uuid.UUID],
        source: Any,
        **kwargs: Any,
    ) -> RepositoryMemory: ...

    async def invalidate_stale(
        self,
        repository_id: uuid.UUID,
        changed_file_paths: Sequence[str],
    ) -> int: ...

    async def save_finding(
        self,
        repository_id: uuid.UUID,
        type: Any,
        content: dict[str, Any],
        evidence_ids: Sequence[uuid.UUID],
        session_id: uuid.UUID | None,
        **kwargs: Any,
    ) -> Finding: ...


from app.memory.service import MemoryService  # noqa: E402

__all__ = ["MemoryService", "MemoryServiceProtocol"]
