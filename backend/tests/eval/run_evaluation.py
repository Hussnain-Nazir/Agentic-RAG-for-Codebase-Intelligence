"""Run deterministic Prism retrieval and grounding evaluation on demo_repo.

The production ingestion, parser, chunker, index, hybrid retriever, tool
registry, and single AgentController are exercised. A deterministic local
hash embedding implements the EmbeddingProvider contract so CI needs no model
download. MockProvider is used only for the generative step: it copies source
excerpts or observed graph facts, making every claim mechanically auditable.
This measures retrieval and grounding, not hosted-model prose quality. No LLM
judge, network credential, or provider call is used.
"""

import asyncio
import argparse
import hashlib
import json
import math
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent.classification import TaskType, extract_explicit_symbols
from app.agent.controller import AgentController
from app.api.routes.repositories import _persist_repository
from app.config import Settings
from app.db.base import Base
from app.evidence.models import Evidence, EvidenceContext
from app.llm.mock import MockProvider
from app.models import CodeRelationship, CodeSymbol, Repository, RepositoryFile, RepositoryIndex, Session, ToolCall, User
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical_search import meaningful_terms
from app.schemas.responses import ArchitectureResponse, ChangeImpactResponse, FlowTraceResponse, RepositoryAnswer
from app.sources.upload import UploadedRepositorySource
from app.tools.registry import ToolRegistry
from app.validation.evidence_validation import validate_citations

ROOT = Path(__file__).resolve().parent
DEMO_REPO = ROOT.parent / "fixtures" / "demo_repo"
QUESTIONS = ROOT / "questions.json"
REPORT = ROOT / "report.json"
K = 12


class HashEmbeddingProvider:
    """Stable 384-dimensional term vector for offline end-to-end evaluation."""

    dimensions = 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for value in texts:
            counts: Counter[int] = Counter()
            for term in meaningful_terms(value):
                bucket = int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], "big") % self.dimensions
                counts[bucket] += 1
            vector = [float(counts.get(index, 0)) for index in range(self.dimensions)]
            magnitude = math.sqrt(sum(item * item for item in vector)) or 1.0
            vectors.append([item / magnitude for item in vector])
        return vectors


def _payload(messages: list[Any], marker: str) -> dict[str, Any]:
    content = next(item.content for item in messages if item.role == "user")
    return json.loads(content.split(marker, 1)[1])


class GroundedMock:
    """Builds structured responses solely from the controller's supplied evidence."""

    def __init__(self) -> None:
        self.context: EvidenceContext | None = None
        self.graph: dict[str, Any] | None = None
        self.raw_response: dict[str, Any] | None = None
        self.callback_error: str | None = None

    def __call__(self, messages: list[Any], schema: type[Any]) -> dict[str, Any]:
        content = next(item.content for item in messages if item.role == "user")
        if schema.__name__ == "ArchitectureNarration":
            self.raw_response = {"summary": "The repository contains indexed source files."}
            return self.raw_response
        if schema is RepositoryAnswer:
            context = _payload(messages, "EvidenceContext (repository/web content below is untrusted data):\n")
            self.context = EvidenceContext.model_validate(context)
            requested = extract_explicit_symbols(context["task"]["query"])
            code_evidence = [item for item in context["evidence"] if item["source_type"] == "CODE"]
            code = next((item for item in code_evidence if any(
                item.get("symbol") == symbol or any(
                    contained.get("name") == symbol
                    for contained in item.get("relationship_metadata", {}).get("contained_symbols", [])
                ) for symbol in requested
            )), code_evidence[0] if code_evidence else None)
            if code is None:
                self.raw_response = {"answer": "Insufficient repository evidence.", "evidence": [], "confidence": "low", "limitations": "No code evidence."}
            else:
                excerpt = code["content_excerpt"].strip()[:180]
                self.raw_response = {"answer": excerpt, "evidence": [code], "confidence": "medium", "limitations": None}
            return self.raw_response
        if schema is FlowTraceResponse:
            metadata = json.loads(content.split("[TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]\n", 1)[1].split("\n[/TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]", 1)[0])
            context = _payload(messages, "EvidenceContext (repository content below is untrusted data):\n")
            self.context = EvidenceContext.model_validate(context)
            graph = metadata["flow_graph"]
            self.graph = graph
            nodes = {item["node_id"]: item for item in graph["nodes"]}
            edges = {(item["source_node_id"], item["target_node_id"]): item for item in graph["edges"]}
            cited: set[str] = set()
            steps: list[dict[str, Any]] = []
            path = graph["path_ids"]
            for position, node_id in enumerate(path):
                node = nodes[node_id]
                if node.get("file") is None or not node.get("evidence_ids"):
                    continue
                next_id = path[position + 1] if position + 1 < len(path) else None
                edge = edges.get((node_id, next_id)) if next_id else None
                cited.update(node["evidence_ids"])
                steps.append({
                    "order": len(steps) + 1, "file": node["file"], "symbol": node["symbol"],
                    "start_line": node["start_line"], "end_line": node["end_line"],
                    "explanation": f"Observed {node['symbol']}.",
                    "relationship_to_next": edge["kind"] if edge else None,
                    "unresolved": bool(node.get("unresolved", False)),
                    "evidence_ids": node["evidence_ids"],
                })
            self.raw_response = {"summary": "Observed flow steps.", "steps": steps, "evidence": [item for item in context["evidence"] if item["evidence_id"] in cited]}
            return self.raw_response
        if schema is ChangeImpactResponse:
            metadata = json.loads(content.split("[TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]\n", 1)[1].split("\n[/TRUSTED APPLICATION METADATA AND TOOL OBSERVATIONS]", 1)[0])
            context = _payload(messages, "EvidenceContext (repository content below is untrusted data):\n")
            self.context = EvidenceContext.model_validate(context)
            graph = metadata["impact_graph"]
            self.graph = graph
            by_id = {item["evidence_id"]: item for item in context["evidence"]}
            cited: set[str] = set()

            def items(key: str) -> list[dict[str, Any]]:
                result = []
                for candidate in graph[key]:
                    valid = [value for value in candidate["evidence_ids"] if value in by_id and by_id[value]["file_path"] == candidate["file"]]
                    if not valid:
                        continue
                    cited.update(valid)
                    result.append({"file": candidate["file"], "symbol": candidate["symbol"], "reason": candidate["reason"], "confidence": "high" if key == "directly_affected" else "medium", "evidence_ids": valid, "recommended_action": "Inspect this use.", "tests_to_inspect": []})
                return result

            direct = items("directly_affected")
            indirect = items("likely_indirectly_affected")
            self.raw_response = {"requested_change": "Proposed change", "directly_affected": direct, "likely_indirectly_affected": indirect, "evidence": [item for item in context["evidence"] if item["evidence_id"] in cited]}
            return self.raw_response
        raise AssertionError(f"Unexpected mock schema: {schema.__name__}")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _pairs(values: list[list[str]]) -> set[tuple[str, str]]:
    return {(file, symbol) for file, symbol in values}


def _ordered_recall(expected: list[list[str]], actual: list[tuple[str, str]]) -> tuple[float, bool]:
    cursor = 0
    found = 0
    for pair in [tuple(item) for item in expected]:
        try:
            cursor = actual.index(pair, cursor) + 1
            found += 1
        except ValueError:
            pass
    order_correct = [item for item in actual if item in _pairs(expected)] == [tuple(item) for item in expected if tuple(item) in actual]
    return _ratio(found, len(expected)), order_correct


def _citation_counts(response: Any, context: EvidenceContext | None) -> tuple[int, int]:
    if context is None or not isinstance(response, (RepositoryAnswer, FlowTraceResponse, ChangeImpactResponse)):
        return 0, 0
    cited = {item.evidence_id for item in response.evidence}
    if isinstance(response, FlowTraceResponse):
        cited.update(value for step in response.steps for value in step.evidence_ids)
    if isinstance(response, ChangeImpactResponse):
        cited.update(value for item in [*response.directly_affected, *response.likely_indirectly_affected] for value in item.evidence_ids)
    removed = set(validate_citations(response, context).removed_citations)
    return len(cited), len(removed)


def _reference_counts(
    category: str, response: Any, graph: dict[str, Any] | None,
    files: dict[str, int], symbols: set[tuple[str, str]],
) -> tuple[int, int]:
    total = invalid = 0
    if category == "symbol" and isinstance(response, list):
        return len(response), sum((item["file_path"], item["name"]) not in symbols for item in response)
    if isinstance(response, FlowTraceResponse):
        nodes = {item["node_id"]: item for item in (graph or {}).get("nodes", [])}
        observed = {
            (nodes[edge["source_node_id"]]["file"], edge["source_symbol"],
             nodes[edge["target_node_id"]]["file"], edge["target_symbol"], edge["kind"])
            for edge in (graph or {}).get("edges", [])
            if edge["source_node_id"] in nodes and edge["target_node_id"] in nodes
        }
        for position, step in enumerate(response.steps):
            total += 1
            invalid += step.file not in files or step.start_line < 1 or step.end_line > files.get(step.file, 0) or (not step.unresolved and (step.file, step.symbol) not in symbols)
            if position + 1 < len(response.steps) and step.relationship_to_next:
                following = response.steps[position + 1]
                total += 1
                invalid += (step.file, step.symbol, following.file, following.symbol, step.relationship_to_next) not in observed
    if isinstance(response, ChangeImpactResponse):
        for item in [*response.directly_affected, *response.likely_indirectly_affected]:
            total += 1
            invalid += (item.file, item.symbol) not in symbols
    return total, invalid


def audit_claims(
    category: str,
    response: Any,
    context: EvidenceContext | None,
    graph: dict[str, Any] | None,
    files: dict[str, int],
    symbols: set[tuple[str, str]],
) -> list[str]:
    """Strict deterministic audit; every unsupported claim or reference is an error."""
    errors: list[str] = []
    if category == "qa":
        if not isinstance(response, RepositoryAnswer) or context is None:
            return ["missing Q&A response or context"]
        checked = validate_citations(response, context)
        if checked.removed_citations:
            errors.append("invalid citation")
        if not response.evidence or not any(response.answer.strip() in item.content_excerpt for item in response.evidence):
            errors.append("unsupported answer claim")
        if context.quality.value == "NONE" and response.confidence != "low":
            errors.append("confident answer without evidence")
    elif category == "flow":
        if not isinstance(response, FlowTraceResponse) or context is None or graph is None:
            return ["missing flow response, context, or observations"]
        removed = validate_citations(response, context).removed_citations
        if removed:
            errors.append("invalid flow citation: " + ",".join(removed))
        graph_nodes = {item["node_id"]: item for item in graph["nodes"]}
        observed = {
            (graph_nodes[edge["source_node_id"]]["file"], edge["source_symbol"],
             graph_nodes[edge["target_node_id"]]["file"], edge["target_symbol"], edge["kind"])
            for edge in graph["edges"]
            if edge["source_node_id"] in graph_nodes and edge["target_node_id"] in graph_nodes
        }
        for index, step in enumerate(response.steps):
            if (not step.unresolved and (step.file, step.symbol) not in symbols) or step.end_line > files.get(step.file, 0):
                errors.append("fabricated flow file, symbol, or line")
            if not step.evidence_ids:
                errors.append("flow step without evidence")
            permitted_explanations = {
                f"Observed {step.symbol}.",
                f"Observed {step.symbol} in the directed flow.",
                f"The investigation could not resolve {step.symbol}.",
            }
            if step.explanation not in permitted_explanations:
                errors.append("unsupported flow explanation")
            if step.unresolved and step.relationship_to_next is not None:
                errors.append("unresolved step claims a transition")
            if index + 1 < len(response.steps) and step.relationship_to_next:
                following = response.steps[index + 1]
                if (step.file, step.symbol, following.file, following.symbol, step.relationship_to_next) not in observed:
                    errors.append("resolved transition absent from observed graph")
    elif category == "impact":
        if not isinstance(response, ChangeImpactResponse) or context is None or graph is None:
            return ["missing impact response, context, or observations"]
        if validate_citations(response, context).removed_citations:
            errors.append("invalid impact citation")
        for key, values in (("directly_affected", response.directly_affected), ("likely_indirectly_affected", response.likely_indirectly_affected)):
            observed = {(item["file"], item["symbol"]): item for item in graph[key]}
            for item in values:
                candidate = observed.get((item.file, item.symbol))
                if (item.file, item.symbol) not in symbols or candidate is None or item.reason != candidate["reason"]:
                    errors.append("unsupported impact claim")
                if not item.evidence_ids:
                    errors.append("impact item without evidence")
    elif category == "symbol":
        for item in response:
            if (item["file_path"], item["name"]) not in symbols:
                errors.append("fabricated symbol")
    elif category == "architecture":
        if not isinstance(response, ArchitectureResponse):
            errors.append("missing architecture response")
    return errors


async def evaluate(*, embedding_provider: Any | None = None, embedding_model_name: str = "prism-eval-hash-v1") -> dict[str, Any]:
    questions: list[dict[str, Any]] = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    embedding = embedding_provider or HashEmbeddingProvider()
    settings = Settings(database_url="sqlite+aiosqlite://", embedding_model_name=embedding_model_name)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            user = User(email="evaluation@example.com", hashed_password="unused")
            db.add(user)
            await db.flush()
            source = UploadedRepositorySource()
            revision = await source.get_revision(str(DEMO_REPO))
            indexing_started = time.perf_counter()
            imported = await _persist_repository(db, user, source, str(DEMO_REPO), revision, "demo_repo", "upload", "upload", embedding, settings)
            indexing_ms = round((time.perf_counter() - indexing_started) * 1000, 2)
            repository_id = uuid.UUID(imported.repository_id)
            index_id = uuid.UUID(imported.index_id)
            repository = await db.get(Repository, repository_id)
            index = await db.get(RepositoryIndex, index_id)
            assert repository is not None and index is not None
            file_rows = list(await db.scalars(select(RepositoryFile).where(RepositoryFile.repository_index_id == index_id)))
            files = {item.path: len((item.content or "").splitlines()) for item in file_rows}
            symbol_rows = list(await db.scalars(select(CodeSymbol).where(CodeSymbol.repository_index_id == index_id)))
            symbols = {(next(file.path for file in file_rows if file.id == item.file_id), item.name) for item in symbol_rows}
            relationships = list(await db.scalars(select(CodeRelationship).where(CodeRelationship.repository_index_id == index_id)))
            retriever = HybridRetriever(session=db, embedding_provider=embedding)
            records: list[dict[str, Any]] = []
            for question in questions:
                started = time.perf_counter()
                text = question["question"]
                candidates = await retriever.retrieve(repository_id, index_id, text)
                top = candidates[:K]
                candidate_files = {item.chunk.file_path for item in top}
                candidate_symbols = {item.chunk.symbol_name for item in top if item.chunk.symbol_name} | {symbol.name for item in top for symbol in item.contained_symbols}
                expected_files = set(question.get("expected_files", []))
                expected_symbols = set(question.get("expected_symbols", []))
                mock = GroundedMock()
                registry = ToolRegistry()
                registry.register_builtin_plugins(session=db, embedding_provider=embedding, settings=settings)
                conversation = Session(user_id=user.id, repository_id=repository_id)
                db.add(conversation)
                await db.flush()
                def mock_callback(messages: list[Any], schema: type[Any]) -> dict[str, Any]:
                    try:
                        return mock(messages, schema)
                    except Exception as exc:
                        mock.callback_error = f"{type(exc).__name__}: {exc}"
                        raise

                controller = AgentController(db, {"A": MockProvider(callback=mock_callback)}, tool_registry=registry, user_id=user.id)
                task_type = {
                    "symbol": TaskType.SYMBOL_LOOKUP,
                    "qa": TaskType.REPOSITORY_QA,
                    "architecture": TaskType.ARCHITECTURE_EXPLANATION,
                    "flow": TaskType.FLOW_TRACE,
                    "impact": TaskType.CHANGE_IMPACT,
                }[question["category"]]
                errors: list[str] = []
                try:
                    result = await controller.run(text, "A", repository_id, conversation.id, task_type_override=task_type)
                    payload = result.result
                    if question["category"] == "symbol":
                        response = payload or []
                    elif question["category"] == "qa":
                        response = RepositoryAnswer.model_validate(payload)
                    elif question["category"] == "flow":
                        response = FlowTraceResponse.model_validate(payload)
                    elif question["category"] == "impact":
                        response = ChangeImpactResponse.model_validate(payload)
                    else:
                        response = ArchitectureResponse.model_validate(payload)
                    errors.extend(audit_claims(question["category"], response, mock.context or result.evidence_context, mock.graph, files, symbols))
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    if mock.callback_error:
                        errors.append(f"Mock callback: {mock.callback_error}")
                    response = None
                    result = None
                tool_count = len(list(await db.scalars(select(ToolCall).where(ToolCall.agent_run_id == result.agent_run_id)))) if result else 0
                response_files: set[str] = set()
                response_symbols: set[str] = set()
                if question["category"] == "symbol" and isinstance(response, list):
                    response_files = {item["file_path"] for item in response}
                    response_symbols = {item["name"] for item in response}
                elif question["category"] == "qa" and isinstance(response, RepositoryAnswer):
                    response_files = {item.file_path for item in response.evidence if item.file_path}
                    response_symbols = {item.symbol for item in response.evidence if item.symbol} | {
                        contained.get("name") for item in response.evidence
                        for contained in item.relationship_metadata.get("contained_symbols", [])
                        if isinstance(contained, dict) and contained.get("name")
                    }
                citation_total, citation_invalid = _citation_counts(response, mock.context or (result.evidence_context if result else None))
                reference_total, reference_invalid = _reference_counts(question["category"], response, mock.graph, files, symbols)
                record: dict[str, Any] = {
                    "id": question["id"], "category": question["category"],
                    "retrieval_hit_at_12": bool(expected_files & candidate_files) if expected_files else None,
                    "retrieval_file_recall": _ratio(len(expected_files & candidate_files), len(expected_files)) if expected_files else None,
                    "retrieval_symbol_recall": _ratio(len(expected_symbols & candidate_symbols), len(expected_symbols)) if expected_symbols else None,
                    "expected_file_recall": _ratio(len(expected_files & response_files), len(expected_files)) if expected_files else None,
                    "expected_symbol_recall": _ratio(len(expected_symbols & response_symbols), len(expected_symbols)) if expected_symbols else None,
                    "citation_total": citation_total, "citation_invalid": citation_invalid,
                    "citation_validity_rate": _ratio(citation_total - citation_invalid, citation_total) if citation_total else None,
                    "evidence_groundedness_rate": 1.0 if response is not None and not any("unsupported" in item or "without evidence" in item or "fabricated" in item or "invalid citation" in item for item in errors) else 0.0,
                    "reference_total": reference_total, "reference_invalid": reference_invalid,
                    "invalid_reference_rate": _ratio(reference_invalid, reference_total) if reference_total else None,
                    "tool_count": tool_count, "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "errors": errors,
                }
                if isinstance(response, FlowTraceResponse):
                    actual = [(item.file, item.symbol) for item in response.steps]
                    recall, ordered = _ordered_recall(question["expected_steps"], actual)
                    record.update(expected_step_recall=recall, step_order_correct=ordered, incorrect_resolved_transitions=sum("resolved transition" in value for value in errors), observed_steps=[{"file": item.file, "symbol": item.symbol, "start_line": item.start_line, "end_line": item.end_line, "unresolved": item.unresolved, "relationship_to_next": item.relationship_to_next} for item in response.steps])
                    if not ordered:
                        errors.append("expected flow steps out of order")
                if isinstance(response, ChangeImpactResponse):
                    for key, label in (("directly_affected", "direct"), ("likely_indirectly_affected", "indirect")):
                        expected = _pairs(question["expected_direct" if label == "direct" else "expected_indirect"])
                        actual = {(item.file, item.symbol) for item in getattr(response, key)}
                        record[f"{label}_recall"] = _ratio(len(actual & expected), len(expected))
                        record[f"{label}_precision"] = _ratio(len(actual & expected), len(actual))
                        record[f"observed_{label}"] = sorted([list(item) for item in actual])
                        if label == "direct" and not expected <= actual:
                            errors.append("known directly affected item omitted")
                        if label == "indirect" and not expected <= actual:
                            errors.append("known indirectly affected item omitted")
                        if label == "indirect" and actual & _pairs(question["expected_direct"]):
                            errors.append("direct item misclassified as indirect")
                if isinstance(response, ArchitectureResponse):
                    record["architecture_languages_match"] = set(question["expected_languages"]).issubset(response.languages)
                    record["architecture_frameworks_match"] = set(question["expected_frameworks"]).issubset(response.frameworks_detected)
                    if not record["architecture_languages_match"] or not record["architecture_frameworks_match"]:
                        errors.append("architecture metadata missed recorded ground truth")
                record["successful"] = not errors and (
                    ((not expected_files or expected_files <= response_files) and (not expected_symbols or expected_symbols <= response_symbols))
                    if question["category"] in ("symbol", "qa") else True
                )
                records.append(record)
            def mean(key: str) -> float:
                values = [item[key] for item in records if item.get(key) is not None]
                return round(sum(values) / len(values), 4) if values else 0.0
            report = {
                "fixture": "backend/tests/fixtures/demo_repo",
                "embedding_provider": type(embedding).__name__,
                "question_count": len(questions), "index_state": index.state.value,
                "indexing_ms": indexing_ms, "indexed_files": len(file_rows),
                "indexed_symbols": len(symbol_rows), "indexed_relationships": len(relationships),
                "metrics": {key: mean(key) for key in (
                    "retrieval_hit_at_12", "retrieval_file_recall", "retrieval_symbol_recall",
                    "expected_file_recall", "expected_symbol_recall",
                    "evidence_groundedness_rate", "expected_step_recall",
                    "step_order_correct", "direct_recall", "direct_precision", "indirect_recall",
                    "indirect_precision", "architecture_languages_match", "architecture_frameworks_match",
                    "tool_count", "latency_ms",
                )},
                "unsuccessful_questions": [item["id"] for item in records if not item["successful"]],
                "questions": records,
            }
            report["metrics"]["citation_validity_rate"] = round(_ratio(
                sum(item["citation_total"] - item["citation_invalid"] for item in records),
                sum(item["citation_total"] for item in records),
            ), 4)
            report["metrics"]["invalid_reference_rate"] = round(_ratio(
                sum(item["reference_invalid"] for item in records),
                sum(item["reference_total"] for item in records),
            ), 4)
            return report
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-embeddings", action="store_true", help="Run a separate manual evaluation with configured LocalEmbeddingProvider")
    args = parser.parse_args()
    output = REPORT
    if args.real_embeddings:
        from app.config import get_settings
        from app.embeddings.local_provider import LocalEmbeddingProvider

        settings = get_settings()
        provider = LocalEmbeddingProvider(settings=settings)
        report = asyncio.run(evaluate(embedding_provider=provider, embedding_model_name=provider.model_name))
        output = ROOT / "report_real_embeddings.json"
    else:
        report = asyncio.run(evaluate())
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "questions"}, indent=2))
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
