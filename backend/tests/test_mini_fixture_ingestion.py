import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.repositories import _persist_repository
from app.config import Settings
from app.db.base import Base
from app.models import (
    CodeChunk,
    CodeRelationship,
    CodeSymbol,
    RepositoryIndex,
    RepositoryIndexState,
    User,
)
from app.retrieval.hybrid import HybridRetriever
from app.sources.upload import UploadedRepositorySource

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_fastapi"


class FakeEmbeddingProvider:
    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, *([0.0] * 383)] for _ in texts]


@pytest.mark.asyncio
async def test_mini_fixture_real_ingestion_populates_structure_and_embeddings() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as session:
            user = User(
                id=uuid.uuid4(),
                email="mini-fixture@example.com",
                hashed_password="unused",
            )
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
                "mini-fastapi",
                "upload",
                "upload",
                FakeEmbeddingProvider(),
                Settings(database_url="sqlite+aiosqlite://"),
            )

            assert response.state is RepositoryIndexState.READY
            index = await session.scalar(select(RepositoryIndex))
            assert index is not None
            chunks = list(await session.scalars(select(CodeChunk)))
            symbols = list(await session.scalars(select(CodeSymbol)))
            relationships = list(await session.scalars(select(CodeRelationship)))

            assert chunks
            assert all(chunk.embedding is not None for chunk in chunks)
            symbol_names = {symbol.name for symbol in symbols}
            assert symbol_names >= {
                "login",
                "create_access_token",
                "verify_password",
                "get_current_user",
                "list_items",
                "create_item",
                "create_session",
                "User",
            }
            by_id = {symbol.id: symbol.name for symbol in symbols}
            relationship_pairs = {
                (by_id[item.from_symbol_id], by_id.get(item.to_symbol_id))
                for item in relationships
            }
            assert relationship_pairs >= {
                ("login", "create_access_token"),
                ("login", "verify_password"),
                ("list_items", "get_current_user"),
                ("list_items", "create_session"),
                ("create_item", "get_current_user"),
            }
            retriever = HybridRetriever(
                session=session,
                embedding_provider=FakeEmbeddingProvider(),
            )
            results = await retriever.retrieve(
                uuid.UUID(response.repository_id),
                uuid.UUID(response.index_id),
                "create_access_token",
            )
            assert results[0].chunk.file_path == "auth/security.py"
            assert any(
                symbol.name == "create_access_token"
                and symbol.match_type == "exact_case_sensitive"
                for symbol in results[0].contained_symbols
            )
            assert {symbol.name for symbol in results[0].contained_symbols} >= {
                "create_access_token",
                "verify_password",
                "get_current_user",
            }
    finally:
        await engine.dispose()
