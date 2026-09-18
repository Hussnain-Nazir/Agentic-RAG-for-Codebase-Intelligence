import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.repository_file import RepositoryFile
    from app.models.repository_index import RepositoryIndex


class CodeChunkType(str, enum.Enum):
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    COMPONENT = "COMPONENT"
    HOOK = "HOOK"
    INTERFACE = "INTERFACE"
    TYPE = "TYPE"
    MODULE_SECTION = "MODULE_SECTION"
    DOCUMENTATION = "DOCUMENTATION"
    FALLBACK = "FALLBACK"


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (
        Index(
            "ix_code_chunks_repository_index",
            "repository_id",
            "repository_index_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_indexes.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    chunk_type: Mapped[CodeChunkType] = mapped_column(
        Enum(CodeChunkType, name="code_chunk_type"),
        nullable=False,
    )
    symbol_name: Mapped[str] = mapped_column(String(255), nullable=True)
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=True)
    parent_symbol: Mapped[str] = mapped_column(String(255), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    repository: Mapped["Repository"] = relationship(back_populates="chunks")
    repository_index: Mapped["RepositoryIndex"] = relationship(back_populates="chunks")
    file: Mapped["RepositoryFile"] = relationship(back_populates="chunks")
