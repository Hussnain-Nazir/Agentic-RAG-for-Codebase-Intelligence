import uuid
from typing import Protocol

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_item import MemoryItem


class MemoryServiceProtocol(Protocol):
    async def retrieve(
        self,
        repository_id: uuid.UUID,
        query: str,
    ) -> list[MemoryItem]: ...

    async def save(
        self,
        repository_id: uuid.UUID,
        repository_index_version: int,
        scope: str,
        topic: str,
        content: str,
    ) -> MemoryItem: ...

    async def invalidate_stale(
        self,
        repository_id: uuid.UUID,
        current_index_version: int,
    ) -> int: ...


class MemoryService:
    """Minimal persistence scaffold pending the dedicated memory phase."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(
        self,
        repository_id: uuid.UUID,
        query: str,
    ) -> list[MemoryItem]:
        pattern = f"%{query}%"
        result = await self._session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.repository_id == repository_id,
                MemoryItem.is_stale.is_(False),
                or_(MemoryItem.topic.ilike(pattern), MemoryItem.content.ilike(pattern)),
            )
            .order_by(MemoryItem.created_at)
        )
        return list(result)

    async def save(
        self,
        repository_id: uuid.UUID,
        repository_index_version: int,
        scope: str,
        topic: str,
        content: str,
    ) -> MemoryItem:
        item = MemoryItem(
            repository_id=repository_id,
            repository_index_version=repository_index_version,
            scope=scope,
            topic=topic,
            content=content,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def invalidate_stale(
        self,
        repository_id: uuid.UUID,
        current_index_version: int,
    ) -> int:
        result = await self._session.execute(
            update(MemoryItem)
            .where(
                MemoryItem.repository_id == repository_id,
                MemoryItem.repository_index_version != current_index_version,
                MemoryItem.is_stale.is_(False),
            )
            .values(is_stale=True)
        )
        return result.rowcount or 0
