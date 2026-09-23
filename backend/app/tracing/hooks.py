import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_execution import ModelExecution, ModelSlot
from app.models.tool_call import ToolCall
from app.tools.base import ExecutionContext

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None


def sanitize_arguments(value: Any, key: str = "") -> Any:
    normalized_key = "".join(character for character in key.lower() if character.isalnum())
    if any(part.replace("_", "") in normalized_key for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, dict):
        return {
            item_key: sanitize_arguments(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_arguments(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_arguments(item) for item in value]
    return value


class HookManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pre_tool(
        self,
        run_id: uuid.UUID,
        seq: int,
        tool_name: str,
        args: dict[str, Any],
        ctx: ExecutionContext,
    ) -> None:
        del ctx
        self._session.add(
            ToolCall(
                agent_run_id=run_id,
                sequence=seq,
                tool_name=tool_name,
                args_sanitized=sanitize_arguments(args),
            )
        )
        await self._session.flush()

    async def post_tool(
        self,
        run_id: uuid.UUID,
        seq: int,
        status: str,
        duration_ms: int,
        result_summary: str,
        error: str | None,
    ) -> None:
        tool_call = await self._session.scalar(
            select(ToolCall).where(
                ToolCall.agent_run_id == run_id,
                ToolCall.sequence == seq,
            )
        )
        if tool_call is None:
            raise LookupError(f"Tool call {seq} does not exist for run {run_id}")
        tool_call.status = status
        tool_call.duration_ms = duration_ms
        tool_call.result_summary = result_summary
        tool_call.error = error
        await self._session.flush()

    async def model_execution(
        self,
        run_id: uuid.UUID,
        slot: Literal["A", "B"],
        model_name: str,
        latency_ms: int,
        tokens: TokenUsage | None,
        validation_status: str,
        error: str | None,
    ) -> None:
        self._session.add(
            ModelExecution(
                agent_run_id=run_id,
                slot=ModelSlot(slot),
                model_name=model_name,
                latency_ms=latency_ms,
                input_tokens=tokens.input_tokens if tokens else None,
                output_tokens=tokens.output_tokens if tokens else None,
                validation_status=validation_status,
                error=error,
            )
        )
        await self._session.flush()
