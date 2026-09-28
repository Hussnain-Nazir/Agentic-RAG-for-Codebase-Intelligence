import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.classification import TaskType, extract_explicit_symbols
from app.agent.controller import (
    MAX_STRUCTURAL_CHUNKS,
    AgentController,
    _BoundsExceeded,
    _Counters,
)
from app.evidence.models import Evidence, EvidenceQuality
from app.llm.base import LLMProvider, Message
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.model_execution import ModelExecution, ModelSlot
from app.models.session import Session
from app.schemas.responses import ModelComparisonResponse, ModelResult, RepositoryAnswer
from app.tools.base import ExecutionContext
from app.tools.errors import UnauthorizedRepositoryAccessError
from app.tools.registry import ToolRegistry
from app.tools.repository_context import authorize_repository
from app.tools.schemas import (
    FindSymbolInput,
    RelatedFilesInput,
    RepositoryQueryInput,
    RetrieveMemoryInput,
)
from app.validation.evidence_validation import validate_citations


class InsufficientComparisonEvidence(RuntimeError):
    pass


def _safe_error(error: Exception) -> str:
    detail = getattr(error, "safe_message", None)
    return f"{type(error).__name__}: " + (
        str(detail) if detail else "selected model request failed"
    )


async def _execution_totals(
    session: AsyncSession, run_id: uuid.UUID, slot: Literal["A", "B"]
) -> tuple[int, int | None, int | None]:
    rows = list(await session.scalars(select(ModelExecution).where(
        ModelExecution.agent_run_id == run_id,
        ModelExecution.slot == ModelSlot(slot),
    )))
    input_values = [row.input_tokens for row in rows if row.input_tokens is not None]
    output_values = [row.output_tokens for row in rows if row.output_tokens is not None]
    return (
        sum(row.latency_ms for row in rows),
        sum(input_values) if input_values else None,
        sum(output_values) if output_values else None,
    )


async def _run_slot(
    slot: Literal["A", "B"],
    provider: LLMProvider | None,
    messages: list[Message],
    context,
    run: AgentRun,
    counters: _Counters,
    controller: AgentController,
    session: AsyncSession,
    timeout_s: int | None,
) -> ModelResult:
    if provider is None:
        error = f"Model {slot} is not configured"
        await controller._hooks.model_execution(
            run.id, slot, "(unconfigured)", 0, None, "NOT_CONFIGURED", error
        )
        return ModelResult(
            slot=slot, model_name="(unconfigured)", response=None,
            latency_ms=0, input_tokens=None, output_tokens=None,
            validation_status="NOT_CONFIGURED", error=error,
        )

    started = time.perf_counter()
    try:
        model_result = await provider.complete(
            messages, schema=RepositoryAnswer,
            timeout_s=timeout_s or getattr(provider, "timeout_s", 60),
        )
    except Exception as exc:
        error = _safe_error(exc)
        latency = max(1, int((time.perf_counter() - started) * 1000))
        await controller._hooks.model_execution(
            run.id, slot, provider.model_name, latency, None, "NOT_VALIDATED", error
        )
        return ModelResult(
            slot=slot, model_name=provider.model_name, response=None,
            latency_ms=latency, input_tokens=None, output_tokens=None,
            validation_status="NOT_VALIDATED", error=error,
        )

    repair_before = counters.repair_attempts
    structured = await controller._validate_or_repair(
        run, counters, slot, provider, model_result,
        RepositoryAnswer, TaskType.REPOSITORY_QA, context,
    )
    latency, input_tokens, output_tokens = await _execution_totals(
        session, run.id, slot
    )
    if structured is None:
        return ModelResult(
            slot=slot, model_name=provider.model_name, response=None,
            latency_ms=latency, input_tokens=input_tokens,
            output_tokens=output_tokens, validation_status="INVALID",
            error="Model answer failed structured validation",
        )

    citation_result = validate_citations(structured, context)
    answer = RepositoryAnswer.model_validate(citation_result.response)
    if citation_result.downgraded and not answer.evidence:
        return ModelResult(
            slot=slot, model_name=provider.model_name, response=None,
            latency_ms=latency, input_tokens=input_tokens,
            output_tokens=output_tokens, validation_status="INVALID_CITATIONS",
            error="Model answer failed grounding validation",
        )
    return ModelResult(
        slot=slot, model_name=provider.model_name,
        response=answer.model_dump(mode="json"), latency_ms=latency,
        input_tokens=input_tokens, output_tokens=output_tokens,
        validation_status=(
            "REPAIRED_VALID" if counters.repair_attempts > repair_before else "VALID"
        ),
        error=None,
    )


async def compare_models(
    repository_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID,
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    providers: dict[Literal["A", "B"], LLMProvider],
    tool_registry: ToolRegistry,
    timeout_s: int | None = None,
) -> ModelComparisonResponse:
    conversation = await session.get(Session, session_id)
    if (
        conversation is None
        or conversation.repository_id != repository_id
        or conversation.user_id != user_id
    ):
        raise UnauthorizedRepositoryAccessError("Session access denied")
    ctx = ExecutionContext(
        repository_id=repository_id, session_id=session_id, user_id=user_id
    )
    await authorize_repository(session, repository_id, ctx)
    run = AgentRun(
        session_id=session_id, task_type="MODEL_COMPARISON",
        status=AgentRunStatus.ERROR,
    )
    session.add(run)
    await session.flush()
    controller = AgentController(
        session, providers, tool_registry=tool_registry,
        user_id=user_id, timeout_s=timeout_s,
    )
    counters = _Counters()
    try:
        memory_result = await controller._execute_tool(
            run, counters, "retrieve_memory",
            RetrieveMemoryInput(
                repository_id=repository_id, scope="repository", query=question
            ), ctx,
        )
        repository_memory = list(getattr(memory_result, "root", []))
        search_result = await controller._execute_tool(
            run, counters, "search_codebase",
            RepositoryQueryInput(repository_id=repository_id, query=question, top_k=12),
            ctx,
        )
        repository_evidence: list[Evidence] = list(getattr(search_result, "root", []))
        qa_entity: str | None = None
        for candidate in extract_explicit_symbols(question):
            symbol_result = await controller._execute_tool(
                run, counters, "find_symbol",
                FindSymbolInput(repository_id=repository_id, symbol_name=candidate),
                ctx,
            )
            if getattr(symbol_result, "root", []):
                qa_entity = candidate
                break
        structural_evidence: list[Evidence] = []
        if qa_entity is not None:
            related = await controller._execute_tool(
                run, counters, "get_related_files",
                RelatedFilesInput(
                    repository_id=repository_id,
                    symbol_name_or_chunk_id=qa_entity,
                ), ctx,
            )
            repository_ids = {item.evidence_id for item in repository_evidence}
            structural_evidence = [
                item for item in getattr(related, "root", [])
                if item.evidence_id not in repository_ids
            ][:MAX_STRUCTURAL_CHUNKS]
        context = controller._context_builder.build_from_evidence(
            question, TaskType.REPOSITORY_QA, repository_memory,
            [*repository_evidence, *structural_evidence], [],
        )
        if context.quality is EvidenceQuality.NONE:
            run.status = AgentRunStatus.OK
            run.completed_at = datetime.now(UTC)
            await session.commit()
            raise InsufficientComparisonEvidence(
                "Insufficient repository evidence was found to compare models"
            )
        metadata = {
            "investigation_goal": f"Investigate {TaskType.REPOSITORY_QA.value}: {question}"
        }
        messages = controller._prompt(
            question, TaskType.REPOSITORY_QA, context, metadata
        )
        results = [
            await _run_slot(
                slot, providers.get(slot), messages, context, run, counters,
                controller, session, timeout_s,
            )
            for slot in ("A", "B")
        ]
        comparison = ModelComparisonResponse(
            agent_run_id=run.id, question=question,
            evidence_context_id=context.context_id, results=results
        )
        run.status = (
            AgentRunStatus.OK if any(item.error is None for item in results)
            else AgentRunStatus.ERROR
        )
        run.completed_at = datetime.now(UTC)
        await session.commit()
        return comparison
    except InsufficientComparisonEvidence:
        raise
    except _BoundsExceeded:
        run.status = AgentRunStatus.BOUNDS_EXCEEDED
        run.completed_at = datetime.now(UTC)
        await session.commit()
        raise
    except Exception:
        run.status = AgentRunStatus.ERROR
        run.completed_at = datetime.now(UTC)
        await session.commit()
        raise
