import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.classification import TaskType
from app.agent.compare import InsufficientComparisonEvidence, compare_models
from app.agent.controller import AgentController, AgentProviderError
from app.api.deps import get_repository_or_404
from app.api.routes.repositories import get_embedding_provider
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.embeddings.base import EmbeddingProvider
from app.evidence.models import EvidenceQuality
from app.llm.base import LLMProvider
from app.llm.factory import get_model_a, get_model_b
from app.models.agent_run import AgentRunStatus
from app.models.repository import Repository
from app.models.session import Session
from app.models.user import User
from app.schemas.responses import ArchitectureResponse, ChangeImpactResponse, FlowTraceResponse, ModelComparisonResponse, RepositoryAnswer
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/repositories", tags=["analysis"])


class AskRepositoryRequest(BaseModel):
    question: str = Field(min_length=1)
    model_slot: Literal["A", "B"]


class AskRepositoryResponse(BaseModel):
    agent_run_id: uuid.UUID
    answer: RepositoryAnswer


class FlowTraceRequest(BaseModel):
    question: str = Field(min_length=1)
    model_slot: Literal["A", "B"]


class FlowTraceApiResponse(BaseModel):
    agent_run_id: uuid.UUID
    trace: FlowTraceResponse


class ChangeImpactRequest(BaseModel):
    change_description: str = Field(min_length=1)
    model_slot: Literal["A", "B"]


class ChangeImpactApiResponse(BaseModel):
    agent_run_id: uuid.UUID
    impact: ChangeImpactResponse


class CompareModelsRequest(BaseModel):
    question: str = Field(min_length=1)


def get_analysis_providers(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[Literal["A", "B"], LLMProvider]:
    providers: dict[Literal["A", "B"], LLMProvider] = {}
    if settings.model_a_name and settings.model_a_base_url and settings.model_a_api_key:
        providers["A"] = get_model_a(settings)
    if settings.model_b_name and settings.model_b_base_url and settings.model_b_api_key:
        providers["B"] = get_model_b(settings)
    return providers


def get_analysis_tool_registry(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    embedding_provider: Annotated[
        EmbeddingProvider,
        Depends(get_embedding_provider),
    ],
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_builtin_plugins(
        session=db,
        embedding_provider=embedding_provider,
        settings=settings,
    )
    return registry


@router.post(
    "/{repository_id}/compare-models",
    response_model=ModelComparisonResponse,
)
async def compare_repository_models(
    repository_id: uuid.UUID,
    request: CompareModelsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    providers: Annotated[
        dict[Literal["A", "B"], LLMProvider], Depends(get_analysis_providers)
    ],
    tool_registry: Annotated[ToolRegistry, Depends(get_analysis_tool_registry)],
) -> ModelComparisonResponse:
    del repository
    conversation = Session(user_id=current_user.id, repository_id=repository_id)
    db.add(conversation)
    await db.flush()
    try:
        comparison = await compare_models(
            repository_id,
            request.question,
            conversation.id,
            session=db,
            user_id=current_user.id,
            providers=providers,
            tool_registry=tool_registry,
        )
    except InsufficientComparisonEvidence as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if all(result.error is not None for result in comparison.results):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Both model comparisons failed",
                "results": [result.model_dump(mode="json") for result in comparison.results],
            },
        )
    return comparison


@router.get("/{repository_id}/architecture", response_model=ArchitectureResponse)
async def explain_architecture(
    repository_id: uuid.UUID,
    model_slot: Literal["A", "B"],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    providers: Annotated[
        dict[Literal["A", "B"], LLMProvider], Depends(get_analysis_providers)
    ],
    tool_registry: Annotated[ToolRegistry, Depends(get_analysis_tool_registry)],
) -> ArchitectureResponse:
    del repository
    if model_slot not in providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model slot {model_slot} is not configured",
        )
    conversation = Session(user_id=current_user.id, repository_id=repository_id)
    db.add(conversation)
    await db.flush()
    try:
        result = await AgentController(
            db, providers, tool_registry=tool_registry, user_id=current_user.id
        ).run(
            "Explain the repository architecture.",
            model_slot,
            repository_id,
            conversation.id,
            task_type_override=TaskType.ARCHITECTURE_EXPLANATION,
        )
    except AgentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "The selected model request failed",
                "agent_run_id": str(exc.run_id),
            },
        ) from exc
    if result.status is not AgentRunStatus.OK:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The model architecture response failed validation",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    return ArchitectureResponse.model_validate(result.result)


@router.post(
    "/{repository_id}/ask",
    response_model=AskRepositoryResponse,
)
async def ask_repository(
    repository_id: uuid.UUID,
    request: AskRepositoryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    providers: Annotated[
        dict[Literal["A", "B"], LLMProvider],
        Depends(get_analysis_providers),
    ],
    tool_registry: Annotated[ToolRegistry, Depends(get_analysis_tool_registry)],
) -> AskRepositoryResponse:
    del repository
    if request.model_slot not in providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model slot {request.model_slot} is not configured",
        )

    conversation = Session(user_id=current_user.id, repository_id=repository_id)
    db.add(conversation)
    await db.flush()
    try:
        result = await AgentController(
            db,
            providers,
            tool_registry=tool_registry,
            user_id=current_user.id,
        ).run(
            request.question,
            request.model_slot,
            repository_id,
            conversation.id,
        )
    except AgentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "The selected model request failed",
                "agent_run_id": str(exc.run_id),
            },
        ) from exc

    if result.task_type not in {TaskType.REPOSITORY_QA, TaskType.EXTERNAL_DOC_QUERY}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The ask endpoint requires a repository Q&A question",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    if (
        result.evidence_context is None
        or result.evidence_context.quality is EvidenceQuality.NONE
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Insufficient repository evidence was found to answer the question",
                "agent_run_id": str(result.agent_run_id),
            },
        )

    if result.status is not AgentRunStatus.OK:
        detail: dict[str, object] = {
            "message": "The model answer failed grounding validation",
            "agent_run_id": str(result.agent_run_id),
        }
        if result.result is not None:
            try:
                answer = RepositoryAnswer.model_validate(result.result)
            except ValidationError:
                pass
            else:
                detail["answer"] = answer.model_dump(mode="json")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )
    answer = RepositoryAnswer.model_validate(result.result)
    return AskRepositoryResponse(agent_run_id=result.agent_run_id, answer=answer)


@router.post(
    "/{repository_id}/flow-trace",
    response_model=FlowTraceApiResponse,
)
async def flow_trace_repository(
    repository_id: uuid.UUID,
    request: FlowTraceRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    providers: Annotated[
        dict[Literal["A", "B"], LLMProvider],
        Depends(get_analysis_providers),
    ],
    tool_registry: Annotated[ToolRegistry, Depends(get_analysis_tool_registry)],
) -> FlowTraceApiResponse:
    del repository
    if request.model_slot not in providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model slot {request.model_slot} is not configured",
        )

    conversation = Session(user_id=current_user.id, repository_id=repository_id)
    db.add(conversation)
    await db.flush()
    try:
        result = await AgentController(
            db,
            providers,
            tool_registry=tool_registry,
            user_id=current_user.id,
        ).run(
            request.question,
            request.model_slot,
            repository_id,
            conversation.id,
        )
    except AgentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "The selected model request failed",
                "agent_run_id": str(exc.run_id),
            },
        ) from exc

    if result.task_type is not TaskType.FLOW_TRACE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The flow-trace endpoint requires a flow-tracing question",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    if (
        result.evidence_context is None
        or result.evidence_context.quality is EvidenceQuality.NONE
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Insufficient repository evidence was found to trace the flow",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    if result.status is AgentRunStatus.INVALID_OUTPUT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The model flow trace failed validation",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    trace = FlowTraceResponse.model_validate(result.result)
    return FlowTraceApiResponse(agent_run_id=result.agent_run_id, trace=trace)


@router.post(
    "/{repository_id}/change-impact",
    response_model=ChangeImpactApiResponse,
)
async def change_impact_repository(
    repository_id: uuid.UUID,
    request: ChangeImpactRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[Repository, Depends(get_repository_or_404)],
    providers: Annotated[
        dict[Literal["A", "B"], LLMProvider],
        Depends(get_analysis_providers),
    ],
    tool_registry: Annotated[ToolRegistry, Depends(get_analysis_tool_registry)],
) -> ChangeImpactApiResponse:
    del repository
    if request.model_slot not in providers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model slot {request.model_slot} is not configured",
        )
    conversation = Session(user_id=current_user.id, repository_id=repository_id)
    db.add(conversation)
    await db.flush()
    try:
        result = await AgentController(
            db,
            providers,
            tool_registry=tool_registry,
            user_id=current_user.id,
        ).run(
            request.change_description,
            request.model_slot,
            repository_id,
            conversation.id,
            task_type_override=TaskType.CHANGE_IMPACT,
        )
    except AgentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "The selected model request failed",
                "agent_run_id": str(exc.run_id),
            },
        ) from exc
    if result.status is AgentRunStatus.INVALID_OUTPUT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The model change impact failed validation",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    if (
        result.evidence_context is None
        or result.evidence_context.quality is EvidenceQuality.NONE
        or not ChangeImpactResponse.model_validate(result.result).directly_affected
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Insufficient repository evidence was found to assess the change",
                "agent_run_id": str(result.agent_run_id),
            },
        )
    return ChangeImpactApiResponse(
        agent_run_id=result.agent_run_id,
        impact=ChangeImpactResponse.model_validate(result.result),
    )
