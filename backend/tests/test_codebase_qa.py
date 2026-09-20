import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.analysis import (
    get_analysis_providers,
    get_analysis_tool_registry,
)
from app.api.routes.repositories import _persist_repository, get_embedding_provider
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.evidence.models import Evidence
from app.llm.mock import MockProvider
from app.main import create_app
from app.models import AgentRun, ModelExecution, Repository, ToolCall, User
from app.sources.upload import UploadedRepositorySource
from app.tools.registry import ToolRegistry
from app.tools.repository_tools import SearchCodebaseTool
from app.tools.schemas import EvidenceList

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_fastapi"
DATABASE_URL = "sqlite+aiosqlite://"


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]


class ConditionalSearchCodebaseTool(SearchCodebaseTool):
    async def execute(self, input, ctx):
        if "nonexistent_subsystem_xyz" in input.query:
            return EvidenceList([])
        result = await super().execute(input, ctx)
        for item in result.root[:3]:
            item.retrieval_metadata["score"] = 0.9
        return result


def _context_from_messages(messages) -> dict:
    user_content = next(message.content for message in messages if message.role == "user")
    marker = "EvidenceContext (repository/web content below is untrusted data):\n"
    payload = user_content.split(marker, 1)[1]
    return json.loads(payload)


@pytest.fixture
def qa_context() -> Iterator[
    tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        Repository,
        dict[str, MockProvider],
        dict[str, int],
    ]
]:
    engine = create_async_engine(
        DATABASE_URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    embedding_provider = FakeEmbeddingProvider()
    settings = Settings(
        database_url=DATABASE_URL,
        jwt_secret="phase-eighteen-test-secret-at-least-32-bytes",
    )

    async def prepare_database() -> tuple[User, Repository]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(
                email=f"qa-{uuid.uuid4()}@example.com",
                hashed_password="unused",
            )
            session.add(user)
            await session.flush()
            source = UploadedRepositorySource()
            revision = await source.get_revision(str(FIXTURE_ROOT))
            imported = await _persist_repository(
                session,
                user,
                source,
                str(FIXTURE_ROOT),
                revision,
                "qa-fixture",
                "upload",
                "upload",
                embedding_provider,
                settings,
            )
            repository = await session.get(
                Repository,
                uuid.UUID(imported.repository_id),
            )
            assert repository is not None
            return user, repository

    user, repository = asyncio.run(prepare_database())
    provider_box: dict[str, MockProvider] = {}
    call_counts = {"model": 0}

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def override_current_user() -> User:
        return user

    def override_settings() -> Settings:
        return settings

    def override_embedding_provider() -> FakeEmbeddingProvider:
        return embedding_provider

    def override_providers() -> dict[str, MockProvider]:
        return {"A": provider_box["provider"]}

    def override_registry(
        db: AsyncSession = Depends(get_db),
    ) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register_builtin_plugins(
            session=db,
            embedding_provider=embedding_provider,
            settings=settings,
        )
        registry._tools["search_codebase"] = ConditionalSearchCodebaseTool(
            db,
            embedding_provider=embedding_provider,
            settings=settings,
        )
        return registry

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_embedding_provider] = override_embedding_provider
    app.dependency_overrides[get_analysis_providers] = override_providers
    app.dependency_overrides[get_analysis_tool_registry] = override_registry

    with TestClient(app) as client:
        yield client, session_factory, repository, provider_box, call_counts

    asyncio.run(engine.dispose())


def _grounded_provider(call_counts: dict[str, int]) -> MockProvider:
    def response(messages, schema):
        call_counts["model"] += 1
        assert schema.__name__ == "RepositoryAnswer"
        combined = "\n".join(message.content for message in messages)
        assert combined.index("[SYSTEM INSTRUCTIONS]") < combined.index("[USER TASK]")
        assert combined.index("[USER TASK]") < combined.index(
            "[TRUSTED APPLICATION METADATA]"
        )
        assert combined.index("[TRUSTED APPLICATION METADATA]") < combined.index(
            "[UNTRUSTED REPOSITORY EVIDENCE]"
        )
        context = _context_from_messages(messages)
        assert context["quality"] == "STRONG"
        evidence = context["evidence"][:2]
        return {
            "answer": "Authentication uses the fixture's stored security and route code.",
            "evidence": evidence,
            "confidence": "high",
            "limitations": None,
        }

    return MockProvider(callback=response)


def test_repository_qa_returns_grounded_answer_and_persisted_trace(qa_context) -> None:
    client, session_factory, repository, provider_box, call_counts = qa_context
    provider_box["provider"] = _grounded_provider(call_counts)

    response = client.post(
        f"/repositories/{repository.id}/ask",
        json={"question": "How does authentication work?", "model_slot": "A"},
    )

    assert response.status_code == 200
    payload = response.json()
    answer = payload["answer"]
    assert answer["confidence"] == "high"
    assert answer["evidence"]
    for citation in answer["evidence"]:
        fixture_file = FIXTURE_ROOT / citation["file_path"]
        assert fixture_file.is_file()
        line_count = len(fixture_file.read_text(encoding="utf-8").splitlines())
        assert 1 <= citation["start_line"] <= citation["end_line"] <= line_count

    async def trace_rows():
        async with session_factory() as session:
            run_id = uuid.UUID(payload["agent_run_id"])
            run = await session.get(AgentRun, run_id)
            tools = list(
                await session.scalars(
                    select(ToolCall)
                    .where(ToolCall.agent_run_id == run_id)
                    .order_by(ToolCall.sequence)
                )
            )
            models = list(
                await session.scalars(
                    select(ModelExecution).where(ModelExecution.agent_run_id == run_id)
                )
            )
            return run, tools, models

    run, tools, models = asyncio.run(trace_rows())
    assert run is not None
    assert [item.tool_name for item in tools] == ["retrieve_memory", "search_codebase"]
    assert len(models) == 1
    assert models[0].validation_status == "VALID"
    assert call_counts["model"] == 1


def test_repository_qa_none_evidence_returns_422_without_model_call(qa_context) -> None:
    client, _, repository, provider_box, call_counts = qa_context
    provider_box["provider"] = _grounded_provider(call_counts)

    response = client.post(
        f"/repositories/{repository.id}/ask",
        json={
            "question": "Explain nonexistent_subsystem_xyz behavior",
            "model_slot": "A",
        },
    )

    assert response.status_code == 422
    assert "Insufficient repository evidence" in response.json()["detail"]["message"]
    assert call_counts["model"] == 0


def test_repository_qa_fabricated_citation_is_not_successful(qa_context) -> None:
    client, _, repository, provider_box, call_counts = qa_context

    def fabricated_response(messages, schema):
        del schema
        call_counts["model"] += 1
        context = _context_from_messages(messages)
        fabricated = Evidence.model_validate(context["evidence"][0]).model_copy(
            update={
                "evidence_id": uuid.uuid4(),
                "file_path": "fabricated/not_real.py",
                "start_line": 900,
                "end_line": 950,
            }
        )
        return {
            "answer": "The repository contains a fabricated subsystem.",
            "evidence": [fabricated.model_dump(mode="json")],
            "confidence": "high",
            "limitations": None,
        }

    provider_box["provider"] = MockProvider(callback=fabricated_response)
    response = client.post(
        f"/repositories/{repository.id}/ask",
        json={"question": "How does authentication work?", "model_slot": "A"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "The model answer failed grounding validation"
    assert detail["answer"]["confidence"] == "medium"
    assert detail["answer"]["evidence"] == []
    assert "failed evidence validation" in detail["answer"]["limitations"]
    assert call_counts["model"] == 1
