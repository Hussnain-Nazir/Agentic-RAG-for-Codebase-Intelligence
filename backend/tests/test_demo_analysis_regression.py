"""Full-stack fixture regressions using the real ingestion path and MockProvider."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.classification import TaskType, extract_explicit_symbols
from app.agent.controller import AgentController
from app.auth.dependencies import get_current_user
from app.config import Settings
from app.db.base import Base
from app.evidence.models import EvidenceQuality
from app.llm.mock import MockProvider
from app.models import AgentRunStatus, ModelExecution, Repository, Session, User
from app.sources.upload import UploadedRepositorySource
from app.api.routes.repositories import _persist_repository
from app.tools.registry import ToolRegistry
from tests.eval.run_evaluation import DEMO_REPO, GroundedMock, HashEmbeddingProvider


QA_QUESTION = (
    "How does this application ensure that an authenticated user can only access "
    "and modify their own items? Explain where authentication is checked, how "
    "items are filtered for the current user, and how unauthorized update or "
    "delete attempts are rejected, citing the relevant files and symbols."
)
FLOW_QUESTION = (
    "Trace the complete login flow from the user submitting the React login form "
    "to the frontend receiving and storing the JWT access token. Show the ordered "
    "path through the frontend API client, FastAPI login route, authentication "
    "service, user lookup, password verification, JWT creation, and the response "
    "back to the React application."
)
IMPACT_QUESTION = (
    "Suppose we change the User model so that a user can belong to multiple "
    "organizations instead of having the single User.organization_id foreign key. "
    "What files and symbols in this repository would need to change directly, "
    "and what areas would likely be affected indirectly? Include the SQLAlchemy "
    "User and Organization relationships, registration schema and registration "
    "logic, frontend registration request, seed/setup code, and tests, with "
    "repository evidence for every affected area."
)


@pytest.fixture(scope="module")
def demo_index():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    embedding = HashEmbeddingProvider()
    settings = Settings(
        _env_file=None, database_url="sqlite+aiosqlite://",
        embedding_model_name="prism-eval-hash-v1",
    )

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            user = User(email="demo-regression@example.com", hashed_password="unused")
            db.add(user)
            await db.flush()
            source = UploadedRepositorySource()
            imported = await _persist_repository(
                db, user, source, str(DEMO_REPO),
                await source.get_revision(str(DEMO_REPO)),
                "demo_regression", "upload", "upload", embedding, settings,
            )
            return user.id, uuid.UUID(imported.repository_id)

    user_id, repository_id = asyncio.run(prepare())
    yield factory, embedding, settings, user_id, repository_id
    asyncio.run(engine.dispose())


def run_demo(demo_index, question: str, task_type: TaskType, callback=None):
    factory, embedding, settings, user_id, repository_id = demo_index
    mock = GroundedMock()

    async def run():
        async with factory() as db:
            conversation = Session(user_id=user_id, repository_id=repository_id)
            db.add(conversation)
            await db.flush()
            registry = ToolRegistry()
            registry.register_builtin_plugins(session=db, embedding_provider=embedding, settings=settings)
            provider = MockProvider(callback=callback or mock)
            result = await AgentController(
                db, {"A": provider}, tool_registry=registry, user_id=user_id,
            ).run(question, "A", repository_id, conversation.id, task_type_override=task_type)
            calls = list(await db.scalars(
                select(ModelExecution).where(ModelExecution.agent_run_id == result.agent_run_id)
            ))
            return result, len(calls)

    result, model_calls = asyncio.run(run())
    return result, model_calls, mock


def test_multi_part_ownership_qa_reaches_model_with_relevant_evidence(demo_index):
    result, calls, _ = run_demo(demo_index, QA_QUESTION, TaskType.REPOSITORY_QA)
    assert result.status is AgentRunStatus.OK
    assert result.evidence_context.quality is not EvidenceQuality.NONE
    assert calls == 1
    paths = {item.file_path for item in result.evidence_context.evidence}
    assert {
        "backend/demo_app/routes/items.py", "backend/demo_app/services.py",
        "backend/demo_app/security.py", "backend/demo_app/repositories.py",
    } <= paths, sorted(paths)
    assert result.result["evidence"]


def test_instruction_words_are_not_symbol_targets():
    assert extract_explicit_symbols("Explain how this works. Trace login. Suppose it changes.") == []


def test_unsupported_multi_part_qa_keeps_no_model_gate(demo_index):
    def unexpected_model(*args):
        raise AssertionError("Unsupported repository question must not call a model")

    question = (
        "How are Stripe payments authorized? Explain where Kubernetes autoscaling "
        "is configured, and how Redis cache invalidation works."
    )
    result, calls, _ = run_demo(demo_index, question, TaskType.REPOSITORY_QA, unexpected_model)
    assert result.evidence_context.quality is EvidenceQuality.NONE
    assert calls == 0


def test_full_login_flow_starts_in_frontend_and_keeps_unproven_links_unresolved(demo_index):
    result, calls, mock = run_demo(demo_index, FLOW_QUESTION, TaskType.FLOW_TRACE)
    assert result.status in {AgentRunStatus.OK, AgentRunStatus.BOUNDS_EXCEEDED}
    assert calls <= 1
    assert mock.graph is not None
    graph = mock.graph
    assert graph["entry_symbol"] == "LoginForm"
    path = graph["path"]
    assert path.index("LoginForm") < path.index("login")
    assert any(edge["kind"] == "API_CALL" for edge in graph["edges"])
    assert {(edge["source_symbol"], edge["target_symbol"]) for edge in graph["edges"]} >= {
        ("authenticate_user", "get_user_by_email"),
        ("authenticate_user", "verify_password"),
    }, graph["edges"]
    steps = result.result["steps"]
    assert any(step["unresolved"] for step in steps)
    assert not any(step["symbol"] == "setToken" for step in steps)
    request_steps = [
        step for step in steps
        if step["file"] == "frontend/src/api.ts" and step["symbol"] == "request"
    ]
    assert request_steps
    for current, following in zip(steps, steps[1:]):
        if current["relationship_to_next"]:
            assert any(
                edge["source_symbol"] == current["symbol"]
                and edge["target_symbol"] == following["symbol"]
                for edge in graph["edges"]
            )


def test_multi_organization_impact_reaches_field_and_consumer_evidence(demo_index):
    result, calls, _ = run_demo(demo_index, IMPACT_QUESTION, TaskType.CHANGE_IMPACT)
    assert result.status is AgentRunStatus.OK
    assert calls == 1
    direct = {(item["file"], item["symbol"]) for item in result.result["directly_affected"]}
    indirect = {(item["file"], item["symbol"]) for item in result.result["likely_indirectly_affected"]}
    assert {
        ("backend/demo_app/models.py", "User.organization_id"),
        ("backend/demo_app/models.py", "User.organization"),
        ("backend/demo_app/models.py", "Organization.users"),
        ("backend/demo_app/schemas.py", "RegisterRequest.organization_id"),
        ("backend/demo_app/services.py", "register_user"),
    } <= direct, sorted(direct)
    assert ("frontend/src/api.ts", "register") in indirect
    assert ("backend/demo_app/seed.py", "main") in indirect
    assert any("test" in path for path, _ in indirect)


@pytest.mark.parametrize("question, expected", [
    ("What is affected if `get_current_user` changes?", ("backend/demo_app/routes/items.py", "list_items")),
    ("What is affected if `create_access_token` changes?", ("backend/demo_app/routes/auth.py", "login")),
])
def test_impact_preserves_observed_consumers_with_larger_expansion(demo_index, question, expected):
    result, calls, mock = run_demo(demo_index, question, TaskType.CHANGE_IMPACT)
    assert result.status is AgentRunStatus.OK
    assert calls == 1
    indirect = {(item["file"], item["symbol"]) for item in result.result["likely_indirectly_affected"]}
    assert expected in indirect, (
        mock.graph["likely_indirectly_affected"],
        [(item.file_path, item.symbol) for item in result.evidence_context.evidence],
    )


def test_nested_architecture_locations_come_from_inspection(demo_index):
    result, calls, _ = run_demo(
        demo_index, "Explain the repository architecture.", TaskType.ARCHITECTURE_EXPLANATION,
    )
    assert result.status is AgentRunStatus.OK and calls == 1
    assert result.result["database_layer"] == "backend/demo_app/db.py"
    assert result.result["api_organization"] == "backend/demo_app/routes"
    assert "backend/demo_app/security.py" in result.result["auth_locations"]
    assert "backend/demo_app/routes/auth.py" in result.result["auth_locations"]
