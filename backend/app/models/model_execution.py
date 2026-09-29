import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent_run import AgentRun


class ModelSlot(str, enum.Enum):
    A = "A"
    B = "B"


class ModelExecution(Base):
    __tablename__ = "model_executions"
    __table_args__ = (Index("ix_model_executions_agent_run_id", "agent_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[ModelSlot] = mapped_column(
        Enum(ModelSlot, name="model_slot"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_validation_status: Mapped[str] = mapped_column(String(64), nullable=True)
    citation_total: Mapped[int] = mapped_column(Integer, nullable=True)
    citation_accepted: Mapped[int] = mapped_column(Integer, nullable=True)
    citation_rejected: Mapped[int] = mapped_column(Integer, nullable=True)
    citation_rejection_reasons: Mapped[dict[str, int]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    error: Mapped[str] = mapped_column(Text, nullable=True)

    agent_run: Mapped["AgentRun"] = relationship(back_populates="model_executions")
