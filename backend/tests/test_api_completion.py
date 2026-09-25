import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text

from app.auth.dependencies import get_current_user
from app.memory.service import MemoryService
from app.models import (
    AgentRun,
    AgentRunStatus,
    CodeChunk,
    CodeRelationship,
    CodeSymbol,
    Finding,
    ModelExecution,
    ModelSlot,
    Repository,
    RepositoryFile,
    RepositoryIndex,
    RepositoryIndexState,
    RepositoryMemory,
    Session,
    ToolCall,
    User,
)
from test_codebase_qa import qa_context


async def _chunk_and_index(factory, repository_id):
    async with factory() as session:
        index = await session.scalar(select(RepositoryIndex).where(
            RepositoryIndex.repository_id == repository_id
        ))
        chunk = await session.scalar(select(CodeChunk).where(
            CodeChunk.repository_id == repository_id
        ))
        assert index is not None and chunk is not None
        return index.id, index.version, chunk.id


def test_repository_listing_detail_status_tree_content_and_symbols(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    base = f"/repositories/{repository.id}"

    listing = client.get("/repositories")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["id"] == str(repository.id)
    assert listing.json()[0]["index"]["state"] == "READY"

    detail = client.get(base)
    assert detail.status_code == 200
    assert detail.json()["owner_id"] == str(repository.owner_id)
    assert detail.json()["source_type"] == "upload"

    status = client.get(f"{base}/index-status")
    assert status.status_code == 200
    assert status.json()["state"] == "READY"
    assert status.json()["files_discovered"] >= 7
    assert status.json()["files_processed"] >= 7

    tree = client.get(f"{base}/files")
    assert tree.status_code == 200
    assert {entry["path"] for entry in tree.json()} >= {
        "auth", "models", "routers", "config.py", "db.py", "README.md"
    }
    nested = client.get(f"{base}/files", params={"path": "auth"})
    assert nested.status_code == 200
    assert [entry["path"] for entry in nested.json()] == ["auth/security.py"]

    content = client.get(f"{base}/files/content", params={"path": "routers/auth.py"})
    assert content.status_code == 200
    assert "def login" in content.json()["content"]
    window = client.get(f"{base}/files/content", params={
        "path": "routers/auth.py", "start_line": 8, "end_line": 10,
    })
    assert window.status_code == 200
    assert window.json()["start_line"] == 8
    assert "def login" in window.json()["content"]

    symbols = client.get(f"{base}/symbols", params={"q": "login"})
    assert symbols.status_code == 200
    assert any(item["name"] == "login" for item in symbols.json())

    async def make_pending():
        async with factory() as session:
            session.add(RepositoryIndex(
                repository_id=repository.id,
                version=2,
                revision="pending-revision",
                state=RepositoryIndexState.PENDING,
                files_discovered=12,
                files_processed=3,
            ))
            await session.commit()

    asyncio.run(make_pending())
    pending = client.get(f"{base}/index-status")
    assert pending.status_code == 200
    assert pending.json()["state"] == "PENDING"
    assert pending.json()["files_discovered"] == 12
    assert pending.json()["files_processed"] == 3


def test_repository_memory_and_findings_endpoints(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    base = f"/repositories/{repository.id}"
    _, _, chunk_id = asyncio.run(_chunk_and_index(factory, repository.id))
    assert client.get(f"{base}/findings").json() == []
    assert client.get(f"{base}/memory").json() == []

    async def seed_memory():
        async with factory() as session:
            service = MemoryService(session)
            current = await service.save_repository_memory(
                repository.id, "FACT", "Login uses a route", [chunk_id], "EXPLICIT"
            )
            stale = await service.save_repository_memory(
                repository.id, "FACT", "Old login fact", [chunk_id], "EXPLICIT"
            )
            stale.is_stale = True
            await session.commit()
            return current.id, stale.id

    current_id, stale_id = asyncio.run(seed_memory())
    active = client.get(f"{base}/memory")
    assert active.status_code == 200
    assert [item["id"] for item in active.json()] == [str(current_id)]
    all_memory = client.get(f"{base}/memory", params={"include_stale": "true"})
    assert all_memory.status_code == 200
    assert {item["id"] for item in all_memory.json()} == {
        str(current_id), str(stale_id)
    }

    created = client.post(f"{base}/findings", json={
        "type": "FLOW_TRACE",
        "content": {"title": "Login trace", "summary": "Fixture result"},
        "evidence_ids": [str(chunk_id)],
    })
    assert created.status_code == 201
    assert created.json()["title"] == "Login trace"
    findings = client.get(f"{base}/findings")
    assert findings.status_code == 200
    assert [item["id"] for item in findings.json()] == [created.json()["id"]]
    invalid = client.post(f"{base}/findings", json={
        "type": "FLOW_TRACE", "content": {"title": "Invalid"},
        "evidence_ids": [str(uuid.uuid4())],
    })
    assert invalid.status_code == 422


def test_evidence_links_resolve_only_current_repository_chunks(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    _, _, chunk_id = asyncio.run(_chunk_and_index(factory, repository.id))
    missing_id = uuid.uuid4()
    path = f"/repositories/{repository.id}/evidence"

    response = client.get(path, params=[("ids", str(chunk_id)), ("ids", str(missing_id))])
    assert response.status_code == 200
    resolved, missing = response.json()
    assert resolved["evidence_id"] == str(chunk_id)
    assert resolved["file_path"]
    assert resolved["start_line"] >= 1
    assert resolved["end_line"] >= resolved["start_line"]
    assert resolved["content_excerpt"]
    assert missing == {
        "evidence_id": str(missing_id), "file_path": None,
        "start_line": None, "end_line": None, "content_excerpt": None,
    }

    async def create_other_repository_chunk() -> uuid.UUID:
        async with factory() as session:
            other = Repository(
                owner_id=repository.owner_id, source_type="upload", name="other",
                default_branch="upload", selected_branch="upload",
            )
            session.add(other)
            await session.flush()
            index = RepositoryIndex(
                repository_id=other.id, version=1, revision="other-revision",
                state=RepositoryIndexState.READY,
            )
            session.add(index)
            await session.flush()
            file = RepositoryFile(
                repository_index_id=index.id, path="other.py", size_bytes=4,
                status="OK", content="pass",
            )
            session.add(file)
            await session.flush()
            chunk = CodeChunk(
                repository_id=other.id, repository_index_id=index.id,
                file_id=file.id, file_path="other.py", language="python",
                chunk_type="MODULE", start_line=1, end_line=1,
                content="pass", content_hash="other-hash",
            )
            session.add(chunk)
            await session.commit()
            return chunk.id

    other_chunk_id = asyncio.run(create_other_repository_chunk())
    cross_repository = client.get(path, params={"ids": str(other_chunk_id)})
    assert cross_repository.status_code == 200
    assert cross_repository.json()[0]["file_path"] is None

    async def supersede_index() -> None:
        async with factory() as session:
            session.add(RepositoryIndex(
                repository_id=repository.id, version=2, revision="new-revision",
                state=RepositoryIndexState.READY,
            ))
            await session.commit()

    asyncio.run(supersede_index())
    stale = client.get(path, params={"ids": str(chunk_id)})
    assert stale.status_code == 200
    assert stale.json()[0]["file_path"] is None


def test_agent_run_detail_and_ordered_trace(qa_context) -> None:
    client, factory, repository, _, _ = qa_context

    async def seed_run():
        async with factory() as session:
            started = datetime(2026, 9, 25, 10, 0)
            conversation = Session(user_id=repository.owner_id, repository_id=repository.id)
            session.add(conversation)
            await session.flush()
            run = AgentRun(session_id=conversation.id, task_type="REPOSITORY_QA", status=AgentRunStatus.OK)
            session.add(run)
            await session.flush()
            session.add_all([
                ToolCall(agent_run_id=run.id, sequence=2, tool_name="find_symbol", args_sanitized={}, status="OK", started_at=started + timedelta(seconds=2), completed_at=started + timedelta(seconds=3)),
                ToolCall(agent_run_id=run.id, sequence=1, tool_name="search_codebase", args_sanitized={}, status="OK", started_at=started, completed_at=started + timedelta(seconds=1)),
                ModelExecution(agent_run_id=run.id, slot=ModelSlot.B, model_name="mock-b", latency_ms=3, validation_status="VALID"),
                ModelExecution(agent_run_id=run.id, slot=ModelSlot.A, model_name="mock-a", latency_ms=2, validation_status="VALID"),
            ])
            await session.commit()
            return run.id, started

    run_id, started = asyncio.run(seed_run())
    detail = client.get(f"/agent-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["repository_id"] == str(repository.id)
    assert detail.json()["status"] == "OK"
    trace = client.get(f"/agent-runs/{run_id}/trace")
    assert trace.status_code == 200
    assert [item["tool_name"] for item in trace.json()["tool_calls"]] == [
        "search_codebase", "find_symbol"
    ]
    assert [datetime.fromisoformat(item["started_at"]) for item in trace.json()["tool_calls"]] == [
        started, started + timedelta(seconds=2)
    ]
    assert all(item["completed_at"] for item in trace.json()["tool_calls"])
    assert [item["slot"] for item in trace.json()["model_executions"]] == ["A", "B"]
    missing = uuid.uuid4()
    assert client.get(f"/agent-runs/{missing}").status_code == 404
    assert client.get(f"/agent-runs/{missing}/trace").status_code == 404

    async def create_other():
        async with factory() as session:
            other = User(email=f"other-{uuid.uuid4()}@example.com", hashed_password="unused")
            session.add(other)
            await session.commit()
            return other

    other = asyncio.run(create_other())
    client.app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(f"/agent-runs/{run_id}").status_code == 403
    assert client.get(f"/agent-runs/{run_id}/trace").status_code == 403


def test_new_repository_endpoints_enforce_404_and_403(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    _, _, chunk_id = asyncio.run(_chunk_and_index(factory, repository.id))

    async def create_other():
        async with factory() as session:
            other = User(email=f"other-{uuid.uuid4()}@example.com", hashed_password="unused")
            session.add(other)
            await session.commit()
            return other

    other = asyncio.run(create_other())
    paths = [
        ("get", ""),
        ("get", "/index-status"),
        ("get", "/files"),
        ("get", "/files/content?path=config.py"),
        ("get", "/symbols?q=login"),
        ("get", "/memory"),
        ("get", f"/evidence?ids={chunk_id}"),
        ("get", "/findings"),
        ("post", "/findings"),
        ("delete", ""),
    ]
    body = {"type": "FLOW_TRACE", "content": {"title": "x"}, "evidence_ids": [str(chunk_id)]}
    missing_id = uuid.uuid4()
    for method, suffix in paths:
        missing = getattr(client, method)(f"/repositories/{missing_id}{suffix}", json=body) if method == "post" else getattr(client, method)(f"/repositories/{missing_id}{suffix}")
        assert missing.status_code == 404, (method, suffix, missing.text)
    client.app.dependency_overrides[get_current_user] = lambda: other
    for method, suffix in paths:
        denied = getattr(client, method)(f"/repositories/{repository.id}{suffix}", json=body) if method == "post" else getattr(client, method)(f"/repositories/{repository.id}{suffix}")
        assert denied.status_code == 403, (method, suffix, denied.text)
    assert client.get("/repositories").json() == []
    del client.app.dependency_overrides[get_current_user]
    assert client.get("/repositories").status_code == 401
    assert client.get(f"/repositories/{repository.id}").status_code == 401


def test_file_api_error_cases(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    base = f"/repositories/{repository.id}"
    assert client.get(f"{base}/files", params={"path": "missing"}).status_code == 404
    assert client.get(f"{base}/files", params={"path": "../auth"}).status_code == 400
    assert client.get(f"{base}/files/content", params={"path": "missing.py"}).status_code == 404
    assert client.get(f"{base}/files/content", params={"path": "../config.py"}).status_code == 400
    assert client.get(f"{base}/files/content", params={"path": "config.py", "start_line": 1}).status_code == 400
    assert client.get(f"{base}/files/content", params={"path": "config.py", "start_line": 1, "end_line": 500}).status_code == 400

    async def add_unsupported_file():
        async with factory() as session:
            index = await session.scalar(select(RepositoryIndex).where(
                RepositoryIndex.repository_id == repository.id
            ))
            session.add(RepositoryFile(
                repository_index_id=index.id,
                path="notes.unsupported",
                status="OK",
                size_bytes=4,
                content="test",
            ))
            await session.commit()

    asyncio.run(add_unsupported_file())
    unsupported = client.get(f"{base}/files/content", params={"path": "notes.unsupported"})
    assert unsupported.status_code == 400


def test_delete_repository_removes_all_existing_dependent_rows(qa_context) -> None:
    client, factory, repository, _, _ = qa_context
    _, _, chunk_id = asyncio.run(_chunk_and_index(factory, repository.id))

    async def seed_and_capture():
        async with factory() as session:
            await session.execute(text("PRAGMA foreign_keys=ON"))
            service = MemoryService(session)
            await service.save_repository_memory(
                repository.id, "FACT", "Login fact", [chunk_id], "EXPLICIT"
            )
            await service.save_finding(
                repository.id, "FLOW_TRACE", {"title": "Saved trace"}, [chunk_id], None
            )
            conversation = Session(user_id=repository.owner_id, repository_id=repository.id)
            session.add(conversation)
            await session.flush()
            run = AgentRun(session_id=conversation.id, task_type="REPOSITORY_QA", status=AgentRunStatus.OK)
            session.add(run)
            await session.flush()
            session.add(ToolCall(agent_run_id=run.id, sequence=1, tool_name="search_codebase", args_sanitized={}))
            session.add(ModelExecution(agent_run_id=run.id, slot=ModelSlot.A, model_name="mock", latency_ms=1, validation_status="VALID"))
            index_ids = list(await session.scalars(select(RepositoryIndex.id).where(
                RepositoryIndex.repository_id == repository.id
            )))
            await session.commit()
            return index_ids, conversation.id, run.id

    index_ids, session_id, run_id = asyncio.run(seed_and_capture())
    async def counts():
        async with factory() as session:
            checks = [
                (Repository, Repository.id == repository.id),
                (RepositoryIndex, RepositoryIndex.repository_id == repository.id),
                (RepositoryFile, RepositoryFile.repository_index_id.in_(index_ids)),
                (CodeChunk, CodeChunk.repository_id == repository.id),
                (CodeSymbol, CodeSymbol.repository_index_id.in_(index_ids)),
                (CodeRelationship, CodeRelationship.repository_index_id.in_(index_ids)),
                (RepositoryMemory, RepositoryMemory.repository_id == repository.id),
                (Finding, Finding.repository_id == repository.id),
                (Session, Session.repository_id == repository.id),
                (AgentRun, AgentRun.session_id == session_id),
                (ToolCall, ToolCall.agent_run_id == run_id),
                (ModelExecution, ModelExecution.agent_run_id == run_id),
            ]
            return {
                model.__tablename__: await session.scalar(
                    select(func.count()).select_from(model).where(predicate)
                )
                for model, predicate in checks
            }

    before = asyncio.run(counts())
    assert all(count > 0 for count in before.values())
    deleted = client.delete(f"/repositories/{repository.id}")
    assert deleted.status_code == 204
    assert client.get(f"/repositories/{repository.id}").status_code == 404

    assert all(count == 0 for count in asyncio.run(counts()).values())
    async def absent_supplementary_tables():
        async with factory() as session:
            result = await session.execute(text(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('supplementary_documents', 'supplementary_document_chunks')"
            ))
            return list(result.scalars())

    # Supplementary-document tables are not yet present in the schema.
    assert asyncio.run(absent_supplementary_tables()) == []
