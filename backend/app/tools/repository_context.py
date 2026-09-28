import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.tools.base import ExecutionContext
from app.tools.errors import (
    IndexNotReadyError,
    RepositoryNotFoundError,
    UnauthorizedRepositoryAccessError,
)


async def authorize_repository(
    session: AsyncSession,
    repository_id: uuid.UUID,
    ctx: ExecutionContext,
) -> Repository:
    repository = await session.get(Repository, repository_id)
    if repository is None:
        raise RepositoryNotFoundError("Repository not found")
    if ctx.user_id is None or repository.owner_id != ctx.user_id:
        raise UnauthorizedRepositoryAccessError("Repository access denied")
    if ctx.repository_id is not None and ctx.repository_id != repository_id:
        raise UnauthorizedRepositoryAccessError("Repository context does not match")
    return repository


async def current_repository_index(
    session: AsyncSession,
    repository_id: uuid.UUID,
) -> RepositoryIndex:
    index = await session.scalar(
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
        raise IndexNotReadyError("Repository index is not ready")
    return index
