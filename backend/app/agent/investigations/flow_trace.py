import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agent.classification import extract_explicit_symbols
from app.evidence.models import Evidence
from app.retrieval.lexical_search import meaningful_terms
from app.schemas.responses import FlowStep, FlowTraceResponse
from app.tools.schemas import FindSymbolInput, RelatedFilesInput

ToolExecutor = Callable[[str, BaseModel], Awaitable[BaseModel]]


@dataclass(slots=True)
class FlowNode:
    symbol: str
    file_path: str | None
    start_line: int | None
    end_line: int | None
    evidence_ids: list[uuid.UUID] = field(default_factory=list)
    unresolved: bool = False


@dataclass(slots=True)
class FlowEdge:
    source_symbol: str
    target_symbol: str
    kind: str
    evidence_ids: list[uuid.UUID]
    observed_by: str
    confidence: str | None = None


@dataclass(slots=True)
class FlowInvestigationState:
    evidence: list[Evidence] = field(default_factory=list)
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    path: list[str] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    visited_symbols: set[str] = field(default_factory=set)
    tool_cache: dict[str, BaseModel] = field(default_factory=dict)
    partial_reason: str | None = None

    def add_evidence(self, items: list[Evidence]) -> None:
        existing = {item.evidence_id for item in self.evidence}
        self.evidence.extend(item for item in items if item.evidence_id not in existing)

    def add_node(self, node: FlowNode) -> None:
        current = self.nodes.get(node.symbol)
        if current is None or (current.unresolved and not node.unresolved) or (
            not current.evidence_ids and node.evidence_ids
        ):
            self.nodes[node.symbol] = node
        if node.symbol not in self.path:
            self.path.append(node.symbol)

    def add_edge(self, edge: FlowEdge) -> None:
        key = (edge.source_symbol, edge.target_symbol, edge.kind)
        if not any(
            (item.source_symbol, item.target_symbol, item.kind) == key
            for item in self.edges
        ):
            self.edges.append(edge)

    def edge_between(self, source: str, target: str) -> FlowEdge | None:
        return next(
            (
                edge
                for edge in self.edges
                if edge.source_symbol == source and edge.target_symbol == target
            ),
            None,
        )

    def ordered_path(self) -> list[str]:
        if not self.path:
            return []
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(symbol: str) -> None:
            if symbol in visited:
                return
            visited.add(symbol)
            ordered.append(symbol)
            for edge in self.edges:
                if edge.source_symbol == symbol and edge.target_symbol in self.nodes:
                    visit(edge.target_symbol)

        visit(self.path[0])
        for symbol in self.path:
            visit(symbol)
        return ordered

    def as_metadata(self) -> dict[str, object]:
        return {
            "entry_symbol": self.path[0] if self.path else None,
            "path": self.ordered_path(),
            "nodes": [
                {
                    "symbol": node.symbol,
                    "file": node.file_path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "unresolved": node.unresolved,
                    "evidence_ids": [str(item) for item in node.evidence_ids],
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source_symbol": edge.source_symbol,
                    "target_symbol": edge.target_symbol,
                    "kind": edge.kind,
                    "confidence": edge.confidence,
                    "observed_by": edge.observed_by,
                    "evidence_ids": [str(item) for item in edge.evidence_ids],
                }
                for edge in self.edges
            ],
            "partial_reason": self.partial_reason,
        }


def _stem(value: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if value.endswith(suffix) and len(value) > len(suffix) + 2:
            return value[: -len(suffix)]
    return value


def _identifier_terms(value: str) -> set[str]:
    parts = re.findall(
        r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+",
        value.replace("_", " "),
    )
    return {_stem(part.lower()) for part in parts if len(part) >= 2}


def _question_terms(task: str) -> set[str]:
    terms = {_stem(item) for item in meaningful_terms(task)}
    words = [_stem(item.lower()) for item in re.findall(r"[A-Za-z]+", task)]
    terms.update(
        left + right
        for left, right in zip(words, words[1:])
        if len(right) <= 3
    )
    return terms


def _candidate_symbols(evidence: list[Evidence]) -> dict[str, dict[str, object]]:
    candidates: dict[str, dict[str, object]] = {}
    for item in evidence:
        if item.symbol:
            candidates.setdefault(
                item.symbol,
                {
                    "file": item.file_path,
                    "route": bool(item.relationship_metadata.get("api_routes")),
                },
            )
        for contained in item.relationship_metadata.get("contained_symbols", []):
            name = contained.get("name")
            if name:
                candidates.setdefault(
                    name,
                    {
                        "file": contained.get("file_path"),
                        "route": False,
                    },
                )
    return candidates


def select_entry_symbol(task: str, evidence: list[Evidence]) -> str | None:
    candidates = _candidate_symbols(evidence)
    explicit = extract_explicit_symbols(task)
    for candidate in explicit:
        exact = next(
            (name for name in candidates if name.lower() == candidate.lower()),
            None,
        )
        if exact:
            return exact
    terms = _question_terms(task)
    raw_words = re.findall(r"[A-Za-z]+", task)
    ignored = {
        "a", "an", "and", "from", "happens", "how", "in", "is", "of",
        "the", "to", "trace", "what", "when", "with",
    }
    words = [
        _stem(word.lower())
        for word in raw_words
        if word.lower() not in ignored
    ]
    guesses: dict[str, int] = {}
    joined_terms: set[str] = set()
    for position, (left, right) in enumerate(zip(words, words[1:])):
        guesses[f"{left}_{right}"] = position
    for position, (left, right) in enumerate(zip(raw_words, raw_words[1:])):
        if right.lower() in {"in", "on", "up", "out"}:
            joined = _stem(left.lower()) + right.lower()
            guesses[joined] = position + len(words)
            joined_terms.add(joined)
    for guess in guesses:
        candidates.setdefault(guess, {"file": None, "route": False})
    route_preference = bool(
        re.search(r"\bwhen\b|\bendpoint\b|\broute\b", task, re.IGNORECASE)
    )
    ranked: list[tuple[int, int, int, int, str]] = []
    for name, metadata in candidates.items():
        name_terms = _identifier_terms(name)
        overlap = len(name_terms.intersection(terms))
        exact_join = int(name.lower() in joined_terms)
        route_bonus = 2 if route_preference and metadata.get("route") else 0
        observed = int(metadata.get("file") is not None)
        ranked.append(
            (overlap + exact_join + route_bonus, overlap + exact_join,
             observed, guesses.get(name, -1), name)
        )
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4]))
    return ranked[0][4] if ranked and ranked[0][0] > 0 else None


def _matching_evidence(
    evidence: list[Evidence],
    *,
    file_path: str | None = None,
    symbol: str | None = None,
) -> list[Evidence]:
    return [
        item
        for item in evidence
        if (file_path is None or item.file_path == file_path)
        and (
            symbol is None
            or item.symbol == symbol
            or symbol in item.content_excerpt
            or any(
                contained.get("name") == symbol
                for contained in item.relationship_metadata.get("contained_symbols", [])
            )
        )
    ]


def _node_from_definition(
    symbol: str,
    definition: object,
    evidence: list[Evidence],
) -> FlowNode:
    matches = _matching_evidence(
        evidence,
        file_path=definition.file_path,
        symbol=symbol,
    )
    supporting = matches[0] if matches else None
    return FlowNode(
        symbol=symbol,
        file_path=definition.file_path,
        start_line=supporting.start_line if supporting else definition.start_line,
        end_line=supporting.end_line if supporting else definition.end_line,
        evidence_ids=[item.evidence_id for item in matches],
    )


async def investigate_flow_trace(
    task: str,
    repository_id: uuid.UUID,
    execute_tool: ToolExecutor,
    state: FlowInvestigationState,
) -> FlowInvestigationState:
    entry = select_entry_symbol(task, state.evidence)
    if entry is None:
        state.partial_reason = "No repository entry symbol matched the flow question."
        return state
    explicit_targets = [
        item for item in extract_explicit_symbols(task) if item.lower() != entry.lower()
    ]
    queue = [entry]

    async def cached_execute(name: str, input_model: BaseModel) -> BaseModel:
        key = f"{name}:{input_model.model_dump_json()}"
        if key not in state.tool_cache:
            state.tool_cache[key] = await execute_tool(name, input_model)
        return state.tool_cache[key]

    while queue:
        current = queue.pop(0)
        if current in state.visited_symbols:
            continue
        state.visited_symbols.add(current)
        definitions = await cached_execute(
            "find_symbol",
            FindSymbolInput(repository_id=repository_id, symbol_name=current),
        )
        exact_definitions = [
            item
            for item in getattr(definitions, "root", [])
            if item.name.lower() == current.lower()
        ]
        if not exact_definitions:
            matches = _matching_evidence(state.evidence, symbol=current)
            supporting = matches[0] if matches else None
            state.add_node(
                FlowNode(
                    symbol=current,
                    file_path=supporting.file_path if supporting else None,
                    start_line=supporting.start_line if supporting else None,
                    end_line=supporting.end_line if supporting else None,
                    evidence_ids=[item.evidence_id for item in matches],
                    unresolved=True,
                )
            )
            break

        definition = exact_definitions[0]
        state.add_node(_node_from_definition(current, definition, state.evidence))
        related = await cached_execute(
            "get_related_files",
            RelatedFilesInput(
                repository_id=repository_id,
                symbol_name_or_chunk_id=current,
                include_seed=True,
            ),
        )
        related_evidence = list(getattr(related, "root", []))
        state.add_evidence(related_evidence)
        state.add_node(_node_from_definition(current, definition, state.evidence))
        raw_edges: list[dict[str, object]] = []
        for item in related_evidence:
            raw_edges.extend(item.relationship_metadata.get("flow_edges", []))
        outgoing: dict[str, dict[str, object]] = {}
        for edge in raw_edges:
            if str(edge.get("source_symbol", "")).lower() != current.lower():
                continue
            target = str(edge.get("target_symbol") or "")
            if target and target not in outgoing:
                outgoing[target] = edge

        source_evidence = _matching_evidence(
            state.evidence,
            file_path=definition.file_path,
            symbol=current,
        )
        source_text = "\n".join(item.content_excerpt for item in source_evidence)
        # PRISM_SPEC.md 23.B: relationship rows prove caller-to-callee links,
        # but do not store call-site lines, so sibling order is not asserted.
        ordered = sorted(outgoing.values(), key=lambda edge: str(edge["target_symbol"]))
        for edge in ordered:
            target = str(edge["target_symbol"])
            matches = _matching_evidence(
                state.evidence,
                file_path=str(edge.get("target_file") or ""),
                symbol=target,
            )
            state.add_node(
                FlowNode(
                    symbol=target,
                    file_path=str(edge.get("target_file") or "") or None,
                    start_line=matches[0].start_line if matches else edge.get("target_start_line"),
                    end_line=matches[0].end_line if matches else edge.get("target_end_line"),
                    evidence_ids=[item.evidence_id for item in matches],
                )
            )
            state.add_edge(
                FlowEdge(
                    source_symbol=current,
                    target_symbol=target,
                    kind=str(edge.get("kind") or "CALLS"),
                    evidence_ids=[item.evidence_id for item in source_evidence],
                    observed_by="get_related_files",
                    confidence=str(edge.get("confidence") or "low"),
                )
            )
            if target not in state.visited_symbols:
                queue.append(target)

        unresolved_target: str | None = None
        if not ordered:
            unresolved_target = next(
                (
                    target
                    for target in explicit_targets
                    if target not in state.visited_symbols and target in source_text
                ),
                None,
            )
            if unresolved_target is None and re.search(
                r"\bexternal\b|\blibrary\b|\bdependency\b", task, re.IGNORECASE
            ):
                qualified = re.search(
                    r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    source_text,
                )
                if qualified:
                    unresolved_target = qualified.group(1)
            if unresolved_target:
                target_definitions = await cached_execute(
                    "find_symbol",
                    FindSymbolInput(
                        repository_id=repository_id,
                        symbol_name=unresolved_target,
                    ),
                )
                if any(
                    item.name.lower() == unresolved_target.lower()
                    for item in getattr(target_definitions, "root", [])
                ):
                    continue
                matches = _matching_evidence(
                    state.evidence,
                    file_path=definition.file_path,
                    symbol=unresolved_target,
                )
                state.add_node(
                    FlowNode(
                        symbol=unresolved_target,
                        file_path=definition.file_path,
                        start_line=matches[0].start_line if matches else definition.start_line,
                        end_line=matches[0].end_line if matches else definition.end_line,
                        evidence_ids=[item.evidence_id for item in matches],
                        unresolved=True,
                    )
                )
                state.add_edge(
                    FlowEdge(
                        source_symbol=current,
                        target_symbol=unresolved_target,
                        kind="CALLS",
                        evidence_ids=[item.evidence_id for item in source_evidence],
                        observed_by="get_related_files",
                        confidence="low",
                    )
                )
                return state

    return state


def deterministic_flow_trace(
    state: FlowInvestigationState,
    evidence: list[Evidence],
    *,
    partial_reason: str | None = None,
) -> FlowTraceResponse:
    steps: list[FlowStep] = []
    available_evidence_ids = {item.evidence_id for item in evidence}
    ordered_path = state.ordered_path()
    for index, symbol in enumerate(ordered_path):
        node = state.nodes[symbol]
        evidence_ids = [
            item for item in node.evidence_ids if item in available_evidence_ids
        ]
        if node.file_path is None or node.start_line is None or node.end_line is None or not evidence_ids:
            continue
        next_symbol = ordered_path[index + 1] if index + 1 < len(ordered_path) else None
        edge = state.edge_between(symbol, next_symbol) if next_symbol else None
        unresolved = node.unresolved
        steps.append(
            FlowStep(
                order=len(steps) + 1,
                file=node.file_path,
                symbol=node.symbol,
                start_line=node.start_line,
                end_line=node.end_line,
                explanation=(
                    f"The investigation could not resolve {node.symbol}."
                    if node.unresolved
                    else f"Observed {node.symbol} in the directed flow."
                ),
                relationship_to_next=edge.kind if edge and not unresolved else None,
                unresolved=unresolved,
                evidence_ids=evidence_ids,
            )
        )
    reason = partial_reason or state.partial_reason
    return FlowTraceResponse(
        summary=(
            f"Partial flow trace: {reason}"
            if reason else
            "Observed caller-to-callee links are shown; sibling steps are separate branches with no established order."
        ),
        steps=steps,
        evidence=evidence,
    )


def partial_flow_trace(state: FlowInvestigationState, evidence: list[Evidence]) -> FlowTraceResponse:
    return deterministic_flow_trace(
        state,
        evidence,
        partial_reason=state.partial_reason or "the configured investigation bound was reached",
    )


def enforce_observed_transitions(
    response: FlowTraceResponse,
    state: FlowInvestigationState,
    evidence: list[Evidence],
) -> FlowTraceResponse:
    data = response.model_dump()
    expected_symbols = [
        symbol
        for symbol in state.ordered_path()
        if symbol in state.nodes
        and state.nodes[symbol].file_path is not None
        and state.nodes[symbol].evidence_ids
    ]
    if [step["symbol"] for step in data["steps"]] != expected_symbols:
        return deterministic_flow_trace(state, evidence)
    if any(not step["evidence_ids"] for step in data["steps"]):
        return deterministic_flow_trace(state, evidence)
    for index, step in enumerate(data["steps"]):
        next_step = data["steps"][index + 1] if index + 1 < len(data["steps"]) else None
        edge = state.edge_between(step["symbol"], next_step["symbol"]) if next_step else None
        node = state.nodes[step["symbol"]]
        if next_step is None:
            step["relationship_to_next"] = None
            step["unresolved"] = node.unresolved
        elif edge is None:
            step["unresolved"] = node.unresolved
            step["relationship_to_next"] = None
        else:
            step["unresolved"] = node.unresolved
            step["relationship_to_next"] = edge.kind
    data["summary"] = (
        f"{data['summary']} Sibling steps are separate branches with no established order."
    )
    return FlowTraceResponse.model_validate(data)
