import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.types import UUIDList

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.session import Session


class FindingType(str, enum.Enum):
    FLOW_TRACE = "FLOW_TRACE"
    IMPACT = "IMPACT"
    REVIEW = "REVIEW"


FINDING_TITLE_MAX_LENGTH = 255
TITLE_ELLIPSIS = "..."


def normalize_finding_title(title: str) -> str:
    if len(title) <= FINDING_TITLE_MAX_LENGTH:
        return title
    limit = FINDING_TITLE_MAX_LENGTH - len(TITLE_ELLIPSIS)
    shortened = title[:limit].rstrip()
    word_boundary = shortened.rfind(" ")
    if word_boundary >= limit // 2:
        shortened = shortened[:word_boundary].rstrip()
    return shortened + TITLE_ELLIPSIS


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_repository_id", "repository_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, name="finding_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(FINDING_TITLE_MAX_LENGTH), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    evidence_ids: Mapped[list[str]] = mapped_column(
        UUIDList(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    repository: Mapped["Repository"] = relationship(back_populates="findings")
    session: Mapped["Session | None"] = relationship(back_populates="findings")

    @validates("title")
    def validate_title(self, _key: str, title: str) -> str:
        return normalize_finding_title(title)
