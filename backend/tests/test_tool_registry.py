import hashlib
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.repositories import _persist_repository
from app.config import Settings
from app.db.base import Base
from app.memory.service import MemoryService
from app.models import (
    Finding,
    FindingType,
    Message,
    MessageRole,
    Repository,
    RepositoryAccessStatus,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    Session,
    User,
    CodeChunk,
)
from app.plugins.file_reading.tool import ReadFileInput, ReadFileRangeInput
from app.plugins.web_search.provider import WebResult
from app.sources.upload import UploadedRepositorySource
from app.tools.base import ExecutionContext
from app.tools.errors import (
    IndexNotReadyError,
    RepositoryNotFoundError,
    UnauthorizedRepositoryAccessError,
)
from app.tools.registry import ToolRegistry
from app.tools.schemas import (
    FindReferencesInput,
    FindSymbolInput,
    InspectRepositoryInput,
    RelatedFilesInput,
    RepositoryQueryInput,
    RetrieveMemoryInput,
    ReviewHistoryInput,
    SaveMemoryInput,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_fastapi"
EXPECTED_TOOLS = [
    "search_codebase",
    "find_symbol",
    "find_references",
    "read_file",
    "read_file_range",
    "get_related_files",
    "inspect_repository",
    "retrieve_memory",
    "save_memory",
    "get_review_history",
    "search_web",
]


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]


class FakeWebProvider:
    async def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        return [
            WebResult(
                title="Official documentation",
                url="https://docs.example.test/",
                snippet=query,
                source_domain="docs.example.test",
            )
        ][:max_results]


@pytest_asyncio.fixture
async def tool_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(email="tools@example.com", hashed_password="unused")
        session.add(user)
        await session.flush()
        source = UploadedRepositorySource()
        revision = await source.get_revision(str(FIXTURE_ROOT))
        response = await _persist_repository(
            session,
            user,
            source,
            str(FIXTURE_ROOT),
            revision,
            "tool-fixture",
            "upload",
            "upload",
            FakeEmbeddingProvider(),
            Settings(database_url="sqlite+aiosqlite://"),
        )
        repository = await session.get(Repository, uuid.UUID(response.repository_id))
        index = await session.get(RepositoryIndex, uuid.UUID(response.index_id))
        assert repository is not None and index is not None
        extra_files = [
            ("package.json", "config", '{"dependencies":{"react":"1","vite":"1"}}'),
            ("requirements.txt", "documentation", "fastapi==0.1\n"),
            ("src/main.tsx", "tsx", "export const App = () => null;\n"),
            ("tests/test_auth.py", "python", "def test_auth(): pass\n"),
        ]
        for path, language, content in extra_files:
            session.add(
                RepositoryFile(
                    repository_index_id=index.id,
                    path=path,
                    language=language,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    status=RepositoryFileStatus.OK,
                    size_bytes=len(content),
                    content=content,
                )
            )
        await session.flush()
        chunks = list(
            await session.scalars(
                select(CodeChunk).where(CodeChunk.repository_index_id == index.id)
            )
        )
        auth_chunk = next(
            chunk for chunk in chunks if chunk.file_path == "auth/security.py"
        )
        memory = await MemoryService(session).save_repository_memory(
            repository.id,
            "FACT",
            "Authentication uses access tokens",
            [auth_chunk.id],
            "EXPLICIT",
            topic="authentication",
        )
        conversation = Session(user_id=user.id, repository_id=repository.id)
        session.add(conversation)
        await session.flush()
        session.add_all(
            [
                Message(
                    session_id=conversation.id,
                    role=MessageRole.USER,
                    content="How does authentication work?",
                ),
                Message(
                    session_id=conversation.id,
                    role=MessageRole.ASSISTANT,
                    content="Authentication uses access tokens.",
                ),
                Finding(
                    repository_id=repository.id,
                    session_id=conversation.id,
                    type=FindingType.REVIEW,
                    title="Review history",
                    content={"category": "maintainability", "detail": "Example"},
                    evidence_ids=[str(auth_chunk.id)],
                ),
            ]
        )
        await session.flush()
        registry = ToolRegistry()
        registry.register_builtin_plugins(
            session=session,
            embedding_provider=FakeEmbeddingProvider(),
            web_search_provider=FakeWebProvider(),
            settings=Settings(database_url="sqlite+aiosqlite://"),
        )
        ctx = ExecutionContext(
            repository_id=repository.id,
            session_id=conversation.id,
            user_id=user.id,
        )
        yield session, registry, ctx, repository, index, auth_chunk, memory
    await engine.dispose()


@pytest.mark.asyncio
async def test_registry_lists_exactly_eleven_real_tools(tool_context) -> None:
    _, registry, _, _, _, _, _ = tool_context

    assert [tool.name for tool in registry.list()] == EXPECTED_TOOLS
    assert all(callable(tool.execute) for tool in registry.list())


@pytest.mark.asyncio
async def test_retrieval_symbol_reference_and_related_tools(tool_context) -> None:
    _, registry, ctx, repository, _, _, _ = tool_context

    search = await registry.get("search_codebase").execute(
        RepositoryQueryInput(
            repository_id=repository.id,
            query="create_access_token",
            top_k=5,
        ),
        ctx,
    )
    symbols = await registry.get("find_symbol").execute(
        FindSymbolInput(
            repository_id=repository.id,
            symbol_name="create_access_token",
        ),
        ctx,
    )
    references = await registry.get("find_references").execute(
        FindReferencesInput(
            repository_id=repository.id,
            symbol_name="create_access_token",
        ),
        ctx,
    )
    related = await registry.get("get_related_files").execute(
        RelatedFilesInput(
            repository_id=repository.id,
            symbol_name_or_chunk_id="create_access_token",
        ),
        ctx,
    )

    assert search.root
    assert search.root[0].repository_id == repository.id
    assert symbols.root[0].name == "create_access_token"
    assert symbols.root[0].match_type == "exact_case_sensitive"
    assert any(item.symbol == "login" for item in references.root)
    assert any(item.file_path == "routers/auth.py" for item in related.root)


@pytest.mark.asyncio
async def test_file_and_architecture_tools_have_real_happy_paths(tool_context) -> None:
    _, registry, ctx, repository, _, _, _ = tool_context

    file_content = await registry.get("read_file").execute(
        ReadFileInput(repository_id=repository.id, path="routers/auth.py"), ctx
    )
    file_range = await registry.get("read_file_range").execute(
        ReadFileRangeInput(
            repository_id=repository.id,
            path="routers/auth.py",
            start_line=1,
            end_line=2,
        ),
        ctx,
    )
    architecture = await registry.get("inspect_repository").execute(
        InspectRepositoryInput(repository_id=repository.id), ctx
    )

    assert "def login" in file_content.content
    assert file_range.content == "from fastapi import APIRouter, HTTPException\n\n"
    assert architecture.frameworks_detected == ["FastAPI", "React", "Vite"]
    assert "src/main.tsx" in architecture.likely_entrypoints
    assert "tests/test_auth.py" in architecture.test_locations


@pytest.mark.asyncio
async def test_memory_and_review_tools_have_real_happy_paths(tool_context) -> None:
    _, registry, ctx, repository, _, auth_chunk, memory = tool_context

    repository_memory = await registry.get("retrieve_memory").execute(
        RetrieveMemoryInput(
            repository_id=repository.id,
            scope="repository",
            query="authentication",
        ),
        ctx,
    )
    session_memory = await registry.get("retrieve_memory").execute(
        RetrieveMemoryInput(
            repository_id=repository.id,
            scope="session",
            query="authentication",
        ),
        ctx,
    )
    saved = await registry.get("save_memory").execute(
        SaveMemoryInput(
            repository_id=repository.id,
            type="FACT",
            content="Login creates an access token",
            evidence_ids=[auth_chunk.id],
        ),
        ctx,
    )
    reviews = await registry.get("get_review_history").execute(
        ReviewHistoryInput(
            repository_id=repository.id,
            category="maintainability",
        ),
        ctx,
    )

    assert repository_memory.root[0].id == memory.id
    assert "Authentication uses access tokens" in session_memory.root[0].content
    assert saved.evidence_ids == [auth_chunk.id]
    assert saved.source == "EXPLICIT"
    assert reviews.root[0].content["category"] == "maintainability"


@pytest.mark.asyncio
async def test_web_tool_executes_real_fake_provider_operation(tool_context) -> None:
    _, registry, ctx, _, _, _, _ = tool_context

    output = await registry.get("search_web").execute(
        {"query": "official docs", "max_results": 5}, ctx
    )

    assert output.results[0].source_domain == "docs.example.test"


@pytest.mark.asyncio
async def test_all_repository_tools_share_not_found_and_access_errors(
    tool_context,
) -> None:
    _, registry, ctx, repository, _, _, _ = tool_context
    missing_id = uuid.uuid4()
    inputs = {
        "search_codebase": RepositoryQueryInput(
            repository_id=missing_id, query="auth"
        ),
        "find_symbol": FindSymbolInput(
            repository_id=missing_id, symbol_name="login"
        ),
        "find_references": FindReferencesInput(
            repository_id=missing_id, symbol_name="login"
        ),
        "read_file": ReadFileInput(repository_id=missing_id, path="auth.py"),
        "read_file_range": ReadFileRangeInput(
            repository_id=missing_id, path="auth.py", start_line=1, end_line=1
        ),
        "get_related_files": RelatedFilesInput(
            repository_id=missing_id, symbol_name_or_chunk_id="login"
        ),
        "inspect_repository": InspectRepositoryInput(repository_id=missing_id),
        "retrieve_memory": RetrieveMemoryInput(
            repository_id=missing_id, scope="repository", query="auth"
        ),
        "save_memory": SaveMemoryInput(
            repository_id=missing_id,
            type="FACT",
            content="fact",
            evidence_ids=[uuid.uuid4()],
        ),
        "get_review_history": ReviewHistoryInput(repository_id=missing_id),
    }
    for name, input_model in inputs.items():
        with pytest.raises(RepositoryNotFoundError):
            await registry.get(name).execute(input_model, ctx)

    wrong_ctx = ExecutionContext(
        repository_id=repository.id,
        session_id=ctx.session_id,
        user_id=uuid.uuid4(),
    )
    with pytest.raises(UnauthorizedRepositoryAccessError):
        await registry.get("inspect_repository").execute(
            InspectRepositoryInput(repository_id=repository.id), wrong_ctx
        )
    with pytest.raises(UnauthorizedRepositoryAccessError):
        await registry.get("retrieve_memory").execute(
            RetrieveMemoryInput(
                repository_id=repository.id,
                scope="session",
                query="auth",
            ),
            ExecutionContext(
                repository_id=repository.id,
                session_id=uuid.uuid4(),
                user_id=ctx.user_id,
            ),
        )


@pytest.mark.asyncio
async def test_index_not_ready_and_input_validation_errors(tool_context) -> None:
    session, registry, ctx, repository, _, _, _ = tool_context
    pending = Repository(
        owner_id=ctx.user_id,
        source_type=RepositorySourceType.UPLOAD,
        name="pending",
        default_branch="upload",
        selected_branch="upload",
        access_status=RepositoryAccessStatus.ACTIVE,
    )
    session.add(pending)
    await session.flush()

    with pytest.raises(IndexNotReadyError):
        await registry.get("inspect_repository").execute(
            InspectRepositoryInput(repository_id=pending.id),
            ExecutionContext(repository_id=pending.id, user_id=ctx.user_id),
        )
    with pytest.raises(ValidationError):
        SaveMemoryInput(
            repository_id=repository.id,
            type="FACT",
            content="missing evidence",
            evidence_ids=[],
        )
