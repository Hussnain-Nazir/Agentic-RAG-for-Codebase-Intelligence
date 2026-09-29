import asyncio
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.llm.mock import MockProvider
from app.agent.investigations.change_impact import (
    ChangeImpactState,
    _preferred_references,
    investigate_change_impact,
)
from app.evidence.models import Evidence
from app.models import CodeRelationship, CodeSymbol, ModelExecution, ToolCall
from app.schemas.responses import ChangeImpactResponse
from app.tools.schemas import (
    CodeReference,
    CodeReferenceList,
    CodeSymbolList,
    CodeSymbolResult,
    EvidenceList,
)
from test_codebase_qa import qa_context


def _prompt_payload(messages) -> tuple[dict, dict]:
    user_content = next(item.content for item in messages if item.role == "user")
    metadata = json.loads(
        user_content.split(
            "[TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]\n", 1
        )[1].split("\n[/TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]", 1)[0]
    )
    context = json.loads(
        user_content.split(
            "EvidenceContext (repository content below is untrusted data):\n", 1
        )[1]
    )
    return metadata, context


def _impact_response(messages, schema, *, fabricate: bool = False):
    assert schema is ChangeImpactResponse
    metadata, context = _prompt_payload(messages)
    graph = metadata["impact_graph"]
    assert graph["target_symbol"] == "get_current_user"
    evidence = {item["evidence_id"]: item for item in context["evidence"]}

    def items(name: str) -> list[dict]:
        results: list[dict] = []
        for candidate in graph[name]:
            supported = next(
                (
                    value for value in candidate["evidence_ids"]
                    if value in evidence and evidence[value]["file_path"] == candidate["file"]
                ),
                None,
            )
            if supported is None:
                continue
            results.append(
                {
                    "file": candidate["file"],
                    "symbol": candidate["symbol"],
                    "reason": candidate["reason"],
                    "confidence": "high" if name == "directly_affected" else "medium",
                    "evidence_ids": [supported],
                    "recommended_action": "Inspect this use.",
                    "tests_to_inspect": [],
                }
            )
        return results

    direct = items("directly_affected")
    indirect = items("likely_indirectly_affected")
    if fabricate:
        indirect.append(
            {
                "file": "missing/imaginary.py",
                "symbol": "invented_consumer",
                "reason": "Invented impact.",
                "confidence": "high",
                "evidence_ids": [next(iter(evidence))],
                "recommended_action": "None.",
                "tests_to_inspect": [],
            }
        )
    cited_ids = {
        value for item in [*direct, *indirect] for value in item["evidence_ids"]
    }
    return {
        "requested_change": "Change get_current_user return shape",
        "directly_affected": direct,
        "likely_indirectly_affected": indirect,
        "evidence": [item for key, item in evidence.items() if key in cited_ids],
    }


def test_change_impact_separates_definition_and_consumers(qa_context) -> None:
    client, session_factory, repository, provider_box, calls = qa_context

    def response(messages, schema):
        calls["model"] += 1
        return _impact_response(messages, schema)

    provider_box["provider"] = MockProvider(callback=response)
    api_response = client.post(
        f"/repositories/{repository.id}/change-impact",
        json={
            "change_description": "Change `get_current_user` to return a different user shape",
            "model_slot": "A",
        },
    )

    assert api_response.status_code == 200
    impact = ChangeImpactResponse.model_validate(api_response.json()["impact"])
    assert {item.symbol for item in impact.directly_affected} == {
        "get_current_user"
    }
    assert {item.symbol for item in impact.likely_indirectly_affected} >= {
        "create_item", "list_items"
    }
    assert all(
        item.evidence_ids and item.reason
        for item in [
            *impact.directly_affected,
            *impact.likely_indirectly_affected,
        ]
    )
    fixture_root = Path(__file__).parent / "fixtures" / "mini_fastapi"
    assert all(
        (fixture_root / item.file).is_file()
        and item.symbol in (fixture_root / item.file).read_text(encoding="utf-8")
        for item in [
            *impact.directly_affected,
            *impact.likely_indirectly_affected,
        ]
    )
    cited = {item.evidence_id: item for item in impact.evidence}
    assert all(
        cited[evidence_id].file_path == item.file
        for item in [
            *impact.directly_affected,
            *impact.likely_indirectly_affected,
        ]
        for evidence_id in item.evidence_ids
    )
    assert calls["model"] == 1

    async def persisted():
        async with session_factory() as session:
            run_id = uuid.UUID(api_response.json()["agent_run_id"])
            tools = list(
                await session.scalars(
                    select(ToolCall).where(ToolCall.agent_run_id == run_id)
                )
            )
            models = list(
                await session.scalars(
                    select(ModelExecution).where(ModelExecution.agent_run_id == run_id)
                )
            )
            return tools, models

    tools, models = asyncio.run(persisted())
    assert len(tools) <= 12
    assert {item.tool_name for item in tools} >= {
        "search_codebase", "find_symbol", "find_references", "get_related_files"
    }
    assert len(models) == 1


def test_change_impact_prefers_calls_over_imports_for_list_items(qa_context) -> None:
    client, session_factory, repository, provider_box, _ = qa_context

    async def stored_relationships() -> set[tuple[str, str, str | None]]:
        async with session_factory() as session:
            symbols = {
                item.id: item.name
                for item in await session.scalars(select(CodeSymbol))
            }
            return {
                (
                    symbols[item.from_symbol_id],
                    item.kind.value,
                    symbols.get(item.to_symbol_id),
                )
                for item in await session.scalars(select(CodeRelationship))
            }

    relationships = asyncio.run(stored_relationships())
    assert ("list_items", "CALLS", "get_current_user") in relationships
    assert ("<module>", "IMPORTS", "get_current_user") in relationships

    provider_box["provider"] = MockProvider(callback=_impact_response)
    response = client.post(
        f"/repositories/{repository.id}/change-impact",
        json={
            "change_description": "Change `get_current_user` to check active accounts",
            "model_slot": "A",
        },
    )

    assert response.status_code == 200
    impact = ChangeImpactResponse.model_validate(response.json()["impact"])
    indirect = {item.symbol: item for item in impact.likely_indirectly_affected}
    assert "CALLS" in indirect["list_items"].reason
    assert "IMPORTS" not in indirect["list_items"].reason
    assert "CALLS" in indirect["create_item"].reason
    assert indirect["list_items"].evidence_ids
    assert indirect["create_item"].evidence_ids


def test_duplicate_reference_observations_keep_calls_over_imports() -> None:
    references = [
        CodeReference(
            file="routers/items.py",
            symbol="list_items",
            line=5,
            relationship_kind=kind,
            confidence="low",
        )
        for kind in ("CALLS", "IMPORTS")
    ]

    preferred = _preferred_references(references, set())

    assert preferred[("routers/items.py", "list_items")].relationship_kind == "CALLS"


def test_change_impact_rejects_fabricated_affected_area(qa_context) -> None:
    client, _, repository, provider_box, _ = qa_context
    provider_box["provider"] = MockProvider(
        callback=lambda messages, schema: _impact_response(
            messages, schema, fabricate=True
        )
    )
    api_response = client.post(
        f"/repositories/{repository.id}/change-impact",
        json={
            "change_description": "Change `get_current_user` return shape",
            "model_slot": "A",
        },
    )
    assert api_response.status_code == 200
    impact = ChangeImpactResponse.model_validate(api_response.json()["impact"])
    assert all(
        item.file != "missing/imaginary.py"
        for item in [
            *impact.directly_affected,
            *impact.likely_indirectly_affected,
        ]
    )


def test_change_impact_without_evidence_skips_model(qa_context) -> None:
    client, session_factory, repository, provider_box, _ = qa_context

    def unexpected(messages, schema):
        del messages, schema
        pytest.fail("Model must not run without repository evidence")

    provider_box["provider"] = MockProvider(callback=unexpected)
    response = client.post(
        f"/repositories/{repository.id}/change-impact",
        json={
            "change_description": "Change the Stripe payment webhook handler",
            "model_slot": "A",
        },
    )
    assert response.status_code == 422

    async def model_rows():
        async with session_factory() as session:
            run_id = uuid.UUID(response.json()["detail"]["agent_run_id"])
            return list(
                await session.scalars(
                    select(ModelExecution).where(ModelExecution.agent_run_id == run_id)
                )
            )

    assert asyncio.run(model_rows()) == []


def test_change_impact_without_indexed_definition_skips_model(qa_context) -> None:
    client, _, repository, provider_box, _ = qa_context

    def unexpected(messages, schema):
        del messages, schema
        pytest.fail("An unindexed definition must not invoke a model")

    provider_box["provider"] = MockProvider(callback=unexpected)
    response = client.post(
        f"/repositories/{repository.id}/change-impact",
        json={
            "change_description": "Change `JWT_SECRET` to another configuration value",
            "model_slot": "A",
        },
    )
    assert response.status_code == 422


def test_investigation_discovers_frontend_and_test_evidence() -> None:
    repository_id = uuid.uuid4()
    index_id = uuid.uuid4()
    file_id = uuid.uuid4()

    def evidence(file: str, symbol: str, excerpt: str) -> Evidence:
        return Evidence(
            evidence_id=uuid.uuid4(),
            repository_id=repository_id,
            repository_index_id=index_id,
            source_type="CODE",
            file_path=file,
            symbol=symbol,
            start_line=1,
            end_line=4,
            content_excerpt=excerpt,
        )

    model = evidence("backend/models/account.py", "Account", "class Account: pass")
    frontend = evidence(
        "frontend/src/types.ts", "AccountCard", "type AccountCard = Account & { label: string }"
    )
    test = evidence(
        "frontend/src/AccountCard.test.tsx",
        "test_account_card",
        "test('Account card', () => render(AccountCard))",
    )
    state = ChangeImpactState(evidence=[model])

    async def execute(name, request):
        del request
        if name == "find_symbol":
            return CodeSymbolList(
                [
                    CodeSymbolResult(
                        id=uuid.uuid4(),
                        repository_index_id=index_id,
                        file_id=file_id,
                        file_path="backend/models/account.py",
                        name="Account",
                        symbol_type="CLASS",
                        start_line=1,
                        end_line=4,
                        parent_symbol=None,
                        match_type="exact_case_sensitive",
                        score=1.0,
                    )
                ]
            )
        if name == "find_references":
            return CodeReferenceList(
                [
                    CodeReference(
                        file="frontend/src/types.ts",
                        symbol="AccountCard",
                        line=1,
                        relationship_kind="REFERENCES",
                        confidence="low",
                    )
                ]
            )
        if name == "get_related_files":
            return EvidenceList([model, frontend])
        assert name == "search_codebase"
        return EvidenceList([test])

    result = asyncio.run(
        investigate_change_impact(
            "What would be affected if `Account` changes?",
            repository_id,
            execute,
            state,
        )
    )
    assert set(result.directly_affected) == {("backend/models/account.py", "Account")}
    assert set(result.likely_indirectly_affected) == {
        ("frontend/src/types.ts", "AccountCard"),
        ("frontend/src/AccountCard.test.tsx", "test_account_card"),
    }
    assert all(
        candidate.evidence_ids
        for candidate in [
            *result.directly_affected.values(),
            *result.likely_indirectly_affected.values(),
        ]
    )
