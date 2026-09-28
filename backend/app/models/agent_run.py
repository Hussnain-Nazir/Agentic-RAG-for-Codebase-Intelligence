import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.model_execution import ModelExecution
    from app.models.session import Session
    from app.models.tool_call import ToolCall


class AgentRunStatus(str, enum.Enum):
    OK = "OK"
    BOUNDS_EXCEEDED = "BOUNDS_EXCEEDED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    ERROR = "ERROR"


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_session_id", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped["Session"] = relationship(back_populates="agent_runs")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    model_executions: Mapped[list["ModelExecution"]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
