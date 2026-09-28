import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.code_chunk import CodeChunk
    from app.models.code_relationship import CodeRelationship
    from app.models.code_symbol import CodeSymbol
    from app.models.repository import Repository
    from app.models.repository_file import RepositoryFile


class RepositoryIndexState(str, enum.Enum):
    PENDING = "PENDING"
    DISCOVERING = "DISCOVERING"
    PARSING = "PARSING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class RepositoryIndex(Base):
    __tablename__ = "repository_indexes"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "version",
            name="uq_repository_indexes_repository_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[RepositoryIndexState] = mapped_column(
        Enum(RepositoryIndexState, name="repository_index_state"),
        default=RepositoryIndexState.PENDING,
        nullable=False,
    )
    files_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_reason: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    repository: Mapped["Repository"] = relationship(back_populates="indexes")
    files: Mapped[list["RepositoryFile"]] = relationship(
        back_populates="repository_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        back_populates="repository_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relationships: Mapped[list["CodeRelationship"]] = relationship(
        back_populates="repository_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        back_populates="repository_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
