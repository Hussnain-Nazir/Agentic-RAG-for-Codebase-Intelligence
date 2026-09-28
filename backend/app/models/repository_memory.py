import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import UUIDList

if TYPE_CHECKING:
    from app.models.repository import Repository


class RepositoryMemoryType(str, enum.Enum):
    FACT = "FACT"
    ARCHITECTURE = "ARCHITECTURE"
    CONVENTION = "CONVENTION"


class RepositoryMemoryConfidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RepositoryMemorySource(str, enum.Enum):
    AUTO = "AUTO"
    EXPLICIT = "EXPLICIT"


class RepositoryMemory(Base):
    __tablename__ = "repository_memories"
    __table_args__ = (
        Index("ix_repository_memories_repository_stale", "repository_id", "is_stale"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    repository_index_version: Mapped[int] = mapped_column(nullable=False)
    type: Mapped[RepositoryMemoryType] = mapped_column(
        Enum(RepositoryMemoryType, name="repository_memory_type"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(
        UUIDList(), nullable=False
    )
    confidence: Mapped[RepositoryMemoryConfidence] = mapped_column(
        Enum(
            RepositoryMemoryConfidence,
            name="repository_memory_confidence",
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    is_stale: Mapped[bool] = mapped_column(default=False, nullable=False)
    source: Mapped[RepositoryMemorySource] = mapped_column(
        Enum(RepositoryMemorySource, name="repository_memory_source"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    repository: Mapped["Repository"] = relationship(back_populates="memories")
