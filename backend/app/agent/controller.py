from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider, Message
from app.models.agent_run import AgentRun, AgentRunStatus
from app.tracing.hooks import HookManager, TokenUsage


class AgentResult(BaseModel):
    answer: str


class AgentController:
    """Phase 4 scaffold proving the persisted model-call path only."""

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        slot: Literal["A", "B"],
        timeout_s: int = 60,
    ) -> None:
        self._session = session
        self._provider = provider
        self._slot = slot
        self._timeout_s = timeout_s
        self._hooks = HookManager(session)

    async def run(self, task: str) -> AgentResult:
        run = AgentRun(
            task_type="REPOSITORY_QA",
            status=AgentRunStatus.ERROR,
        )
        self._session.add(run)
        await self._session.flush()

        try:
            model_result = await self._provider.complete(
                messages=[Message(role="user", content=task)],
                schema=AgentResult,
                timeout_s=self._timeout_s,
            )
            validated = AgentResult.model_validate_json(model_result.content)
        except ValidationError as exc:
            run.status = AgentRunStatus.INVALID_OUTPUT
            run.completed_at = datetime.now(timezone.utc)
            await self._hooks.model_execution(
                run_id=run.id,
                slot=self._slot,
                model_name=self._provider.model_name,
                latency_ms=0,
                tokens=None,
                validation_status="INVALID",
                error=str(exc),
            )
            await self._session.commit()
            raise
        except Exception as exc:
            run.status = AgentRunStatus.ERROR
            run.completed_at = datetime.now(timezone.utc)
            await self._hooks.model_execution(
                run_id=run.id,
                slot=self._slot,
                model_name=self._provider.model_name,
                latency_ms=0,
                tokens=None,
                validation_status="NOT_VALIDATED",
                error=str(exc),
            )
            await self._session.commit()
            raise

        run.status = AgentRunStatus.OK
        run.completed_at = datetime.now(timezone.utc)
        await self._hooks.model_execution(
            run_id=run.id,
            slot=self._slot,
            model_name=self._provider.model_name,
            latency_ms=model_result.latency_ms,
            tokens=TokenUsage(
                input_tokens=model_result.input_tokens,
                output_tokens=model_result.output_tokens,
            ),
            validation_status="VALID",
            error=None,
        )
        await self._session.commit()
        return validated
