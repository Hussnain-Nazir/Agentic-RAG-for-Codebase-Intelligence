import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.code_symbol import CodeSymbol
    from app.models.repository_index import RepositoryIndex


class CodeRelationshipKind(str, enum.Enum):
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    REFERENCES = "REFERENCES"
    API_CALL = "API_CALL"
    EXTENDS = "EXTENDS"


class CodeRelationshipConfidence(str, enum.Enum):
    HIGH = "high"
    LOW = "low"


class CodeRelationship(Base):
    __tablename__ = "code_relationships"
    __table_args__ = (
        Index("ix_code_relationships_from_symbol_id", "from_symbol_id"),
        Index("ix_code_relationships_to_symbol_id", "to_symbol_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_indexes.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_symbol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[CodeRelationshipKind] = mapped_column(
        Enum(CodeRelationshipKind, name="code_relationship_kind"),
        nullable=False,
    )
    confidence: Mapped[CodeRelationshipConfidence] = mapped_column(
        Enum(
            CodeRelationshipConfidence,
            name="code_relationship_confidence",
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )

    repository_index: Mapped["RepositoryIndex"] = relationship(
        back_populates="relationships"
    )
    from_symbol: Mapped["CodeSymbol"] = relationship(
        foreign_keys=[from_symbol_id],
        back_populates="outgoing_relationships",
    )
    to_symbol: Mapped["CodeSymbol | None"] = relationship(
        foreign_keys=[to_symbol_id],
        back_populates="incoming_relationships",
    )
