import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repository_or_404
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.model_execution import ModelExecution, ModelSlot
from app.models.session import Session
from app.models.tool_call import ToolCall
from app.models.user import User


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


class AgentRunDetail(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    session_id: uuid.UUID
    task_type: str
    status: AgentRunStatus
    started_at: datetime
    completed_at: datetime | None


class ToolCallDetail(BaseModel):
    id: uuid.UUID
    sequence: int
    tool_name: str
    args_sanitized: dict[str, Any]
    status: str | None
    duration_ms: int | None
    result_summary: str | None
    error: str | None


class ModelExecutionDetail(BaseModel):
    id: uuid.UUID
    slot: ModelSlot
    model_name: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    validation_status: str
    error: str | None


class AgentTrace(BaseModel):
    run: AgentRunDetail
    tool_calls: list[ToolCallDetail]
    model_executions: list[ModelExecutionDetail]


async def get_owned_agent_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> tuple[AgentRun, Session]:
    run = await db.get(AgentRun, run_id)
    if run is None or run.session_id is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    conversation = await db.get(Session, run.session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    await get_repository_or_404(conversation.repository_id, db, current_user)
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Agent run access denied")
    return run, conversation


def _run_detail(run: AgentRun, conversation: Session) -> AgentRunDetail:
    return AgentRunDetail(
        id=run.id,
        repository_id=conversation.repository_id,
        session_id=conversation.id,
        task_type=run.task_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.get("/{run_id}", response_model=AgentRunDetail)
async def get_agent_run(
    owned: Annotated[tuple[AgentRun, Session], Depends(get_owned_agent_run)],
) -> AgentRunDetail:
    run, conversation = owned
    return _run_detail(run, conversation)


@router.get("/{run_id}/trace", response_model=AgentTrace)
async def get_agent_trace(
    db: Annotated[AsyncSession, Depends(get_db)],
    owned: Annotated[tuple[AgentRun, Session], Depends(get_owned_agent_run)],
) -> AgentTrace:
    run, conversation = owned
    tools = list(await db.scalars(
        select(ToolCall)
        .where(ToolCall.agent_run_id == run.id)
        .order_by(ToolCall.sequence, ToolCall.id)
    ))
    models = list(await db.scalars(
        select(ModelExecution)
        .where(ModelExecution.agent_run_id == run.id)
        .order_by(ModelExecution.slot, ModelExecution.id)
    ))
    return AgentTrace(
        run=_run_detail(run, conversation),
        tool_calls=[ToolCallDetail.model_validate(item, from_attributes=True) for item in tools],
        model_executions=[
            ModelExecutionDetail.model_validate(item, from_attributes=True)
            for item in models
        ],
    )
