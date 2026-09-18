import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.ingestion.parsing_stage import parse_repository_files
from app.models import (
    CodeRelationship,
    CodeRelationshipConfidence,
    CodeRelationshipKind,
    CodeSymbol,
    Repository,
    RepositoryFile,
    RepositoryFileStatus,
    RepositoryIndex,
    RepositoryIndexState,
    RepositorySourceType,
    User,
)
from app.parsing.javascript_parser import JavaScriptTreeSitterParser
from app.parsing.python_parser import PythonTreeSitterParser
from app.parsing.relationships import extract_relationships
from app.parsing.typescript_parser import TypeScriptTreeSitterParser

FIXTURES = Path(__file__).parent / "fixtures" / "parsing"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_python_extracts_functions_methods_class_route_and_relationships() -> None:
    parsed = PythonTreeSitterParser().parse(fixture_text("sample.py"), "sample.py")

    symbols = {(item.name, item.symbol_type, item.parent_symbol) for item in parsed.symbols}
    assert parsed.parse_ok is True
    assert ("helper", "FUNCTION", None) in symbols
    assert ("Greeter", "CLASS", None) in symbols
    assert ("greet", "METHOD", "Greeter") in symbols
    assert ("health", "FUNCTION", None) in symbols
    assert parsed.metadata["api_routes"]

    relationships = extract_relationships(parsed)
    assert any(
        item.from_symbol == "greet"
        and item.to_symbol == "helper"
        and item.kind is CodeRelationshipKind.CALLS
        and item.confidence is CodeRelationshipConfidence.HIGH
        for item in relationships
    )


def test_javascript_extracts_component_hook_imports_and_exports() -> None:
    parsed = JavaScriptTreeSitterParser(jsx=True).parse(
        fixture_text("sample.jsx"),
        "sample.jsx",
    )

    symbols = {(item.name, item.symbol_type) for item in parsed.symbols}
    assert parsed.parse_ok is True
    assert ("LoginForm", "COMPONENT") in symbols
    assert ("useLogin", "HOOK") in symbols
    assert parsed.imports[0].module == "./api"
    assert set(parsed.exports) == {"LoginForm", "useLogin"}


def test_typescript_extracts_interface_type_function_and_api_call() -> None:
    parsed = TypeScriptTreeSitterParser().parse(
        fixture_text("sample.ts"),
        "sample.ts",
    )

    symbols = {(item.name, item.symbol_type) for item in parsed.symbols}
    assert parsed.parse_ok is True
    assert ("User", "INTERFACE") in symbols
    assert ("UserId", "TYPE") in symbols
    assert ("loadUser", "FUNCTION") in symbols
    load_user = next(item for item in parsed.symbols if item.name == "loadUser")
    assert load_user.metadata["api_calls"] == ["/api/users/1"]


@pytest.mark.parametrize(
    ("filename", "parser"),
    [
        ("malformed.py", PythonTreeSitterParser()),
        ("malformed.js", JavaScriptTreeSitterParser()),
        ("malformed.ts", TypeScriptTreeSitterParser()),
    ],
)
def test_malformed_files_always_return_fallback(filename: str, parser: object) -> None:
    parsed = parser.parse(fixture_text(filename), filename)

    assert parsed.parse_ok is False
    assert parsed.fallback_used is True
    assert parsed.metadata["chunk_type"] == "FALLBACK"
    assert parsed.metadata["start_line"] == 1
    assert parsed.metadata["end_line"] >= 1


@pytest.mark.asyncio
async def test_repository_parse_isolates_malformed_file_and_persists_other_symbols() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(email="parser@example.com", hashed_password="unused")
        session.add(user)
        await session.flush()
        repository = Repository(
            owner_id=user.id,
            source_type=RepositorySourceType.UPLOAD,
            name="fixture",
            default_branch="upload",
            selected_branch="upload",
        )
        session.add(repository)
        await session.flush()
        index = RepositoryIndex(
            repository_id=repository.id,
            version=1,
            revision="fixture",
            state=RepositoryIndexState.PARSING,
        )
        session.add(index)
        await session.flush()
        valid = RepositoryFile(
            repository_index_id=index.id,
            path="sample.py",
            language="python",
            content_hash="a" * 64,
            status=RepositoryFileStatus.OK,
            size_bytes=len(fixture_text("sample.py")),
            content=fixture_text("sample.py"),
        )
        malformed = RepositoryFile(
            repository_index_id=index.id,
            path="malformed.ts",
            language="typescript",
            content_hash="b" * 64,
            status=RepositoryFileStatus.OK,
            size_bytes=len(fixture_text("malformed.ts")),
            content=fixture_text("malformed.ts"),
        )
        session.add_all([valid, malformed])
        await session.flush()

        parsed = await parse_repository_files([valid, malformed])

        assert len(parsed) == 2
        assert malformed.status is RepositoryFileStatus.PARSE_FAILED
        symbols = list(await session.scalars(select(CodeSymbol)))
        assert {item.name for item in symbols} >= {"helper", "Greeter", "greet", "health"}
        relationships = list(await session.scalars(select(CodeRelationship)))
        assert relationships
        by_id = {item.id: item for item in symbols}
        for relationship in relationships:
            if relationship.confidence is CodeRelationshipConfidence.HIGH:
                assert relationship.to_symbol_id is not None
                assert by_id[relationship.from_symbol_id].file_id == by_id[relationship.to_symbol_id].file_id

    await engine.dispose()
