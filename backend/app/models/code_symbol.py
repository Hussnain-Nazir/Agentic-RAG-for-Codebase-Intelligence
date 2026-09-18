import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.code_relationship import CodeRelationship
    from app.models.repository_file import RepositoryFile
    from app.models.repository_index import RepositoryIndex


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (
        Index("ix_code_symbols_index_name", "repository_index_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_indexes.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_symbol: Mapped[str] = mapped_column(String(255), nullable=True)

    repository_index: Mapped["RepositoryIndex"] = relationship(back_populates="symbols")
    file: Mapped["RepositoryFile"] = relationship(back_populates="symbols")
    outgoing_relationships: Mapped[list["CodeRelationship"]] = relationship(
        foreign_keys="CodeRelationship.from_symbol_id",
        back_populates="from_symbol",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    incoming_relationships: Mapped[list["CodeRelationship"]] = relationship(
        foreign_keys="CodeRelationship.to_symbol_id",
        back_populates="to_symbol",
        passive_deletes=True,
    )
