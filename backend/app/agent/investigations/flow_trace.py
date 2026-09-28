import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agent.classification import extract_explicit_symbols
from app.evidence.models import Evidence
from app.retrieval.lexical_search import meaningful_terms
from app.schemas.responses import FlowStep, FlowTraceResponse
from app.tools.schemas import FindReferencesInput, FindSymbolInput, RelatedFilesInput

ToolExecutor = Callable[[str, BaseModel], Awaitable[BaseModel]]


@dataclass(slots=True)
class FlowNode:
    node_id: str
    symbol: str
    symbol_id: uuid.UUID | None
    file_path: str | None
    start_line: int | None
    end_line: int | None
    evidence_ids: list[uuid.UUID] = field(default_factory=list)
    unresolved: bool = False
    definition_line: int | None = None


@dataclass(slots=True)
class FlowEdge:
    source_id: str
    target_id: str
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
    visited_nodes: set[str] = field(default_factory=set)
    reference_observations: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    tool_cache: dict[str, BaseModel] = field(default_factory=dict)
    partial_reason: str | None = None

    def add_evidence(self, items: list[Evidence]) -> None:
        existing = {item.evidence_id for item in self.evidence}
        self.evidence.extend(item for item in items if item.evidence_id not in existing)

    def add_node(self, node: FlowNode) -> None:
        current = self.nodes.get(node.node_id)
        if current is None or (current.unresolved and not node.unresolved) or (
            not current.evidence_ids and node.evidence_ids
        ):
            self.nodes[node.node_id] = node
        if node.node_id not in self.path:
            self.path.append(node.node_id)

    def add_edge(self, edge: FlowEdge) -> None:
        key = (edge.source_id, edge.target_id, edge.kind)
        if not any(
            (item.source_id, item.target_id, item.kind) == key
            for item in self.edges
        ):
            self.edges.append(edge)

    def edge_between(self, source_id: str, target_id: str) -> FlowEdge | None:
        return next(
            (
                edge
                for edge in self.edges
                if edge.source_id == source_id and edge.target_id == target_id
            ),
            None,
        )

    def ordered_path(self) -> list[str]:
        if not self.path:
            return []
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            ordered.append(node_id)
            for edge in self.edges:
                if edge.source_id == node_id and edge.target_id in self.nodes:
                    visit(edge.target_id)

        visit(self.path[0])
        for node_id in self.path:
            visit(node_id)
        return ordered

    def as_metadata(self) -> dict[str, object]:
        return {
            "entry_symbol": self.nodes[self.path[0]].symbol if self.path else None,
            "path": [self.nodes[item].symbol for item in self.ordered_path()],
            "path_ids": self.ordered_path(),
            "nodes": [
                {
                    "symbol": node.symbol,
                    "node_id": node.node_id,
                    "symbol_id": str(node.symbol_id) if node.symbol_id else None,
                    "file": node.file_path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "definition_line": node.definition_line,
                    "unresolved": node.unresolved,
                    "evidence_ids": [str(item) for item in node.evidence_ids],
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source_symbol": edge.source_symbol,
                    "target_symbol": edge.target_symbol,
                    "source_node_id": edge.source_id,
                    "target_node_id": edge.target_id,
                    "kind": edge.kind,
                    "confidence": edge.confidence,
                    "observed_by": edge.observed_by,
                    "evidence_ids": [str(item) for item in edge.evidence_ids],
                }
                for edge in self.edges
            ],
            "partial_reason": self.partial_reason,
            "reference_observations": self.reference_observations,
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
        node_id=str(definition.id),
        symbol=symbol,
        symbol_id=definition.id,
        file_path=definition.file_path,
        start_line=supporting.start_line if supporting else definition.start_line,
        end_line=supporting.end_line if supporting else definition.end_line,
        evidence_ids=[item.evidence_id for item in matches],
        definition_line=definition.start_line,
    )


async def investigate_flow_trace(
    task: str,
    repository_id: uuid.UUID,
    execute_tool: ToolExecutor,
    state: FlowInvestigationState,
    available_tool_calls: int = 6,
) -> FlowInvestigationState:
    entry = select_entry_symbol(task, state.evidence)
    if entry is None:
        state.partial_reason = "No repository entry symbol matched the flow question."
        return state
    explicit_targets = [
        item for item in extract_explicit_symbols(task) if item.lower() != entry.lower()
    ]
    calls_used = 0

    async def cached_execute(name: str, input_model: BaseModel) -> BaseModel | None:
        nonlocal calls_used
        key = f"{name}:{input_model.model_dump_json()}"
        if key not in state.tool_cache:
            if calls_used >= available_tool_calls:
                return None
            calls_used += 1
            state.tool_cache[key] = await execute_tool(name, input_model)
        return state.tool_cache[key]

    definitions = await cached_execute(
        "find_symbol",
        FindSymbolInput(repository_id=repository_id, symbol_name=entry),
    )
    exact_definitions = [
        item for item in getattr(definitions, "root", [])
        if item.name.lower() == entry.lower()
    ]
    if not exact_definitions:
        state.partial_reason = "No exact repository definition matched the entry symbol."
        return state

    def definition_order(definition: object) -> tuple[float, str, str]:
        matches = _matching_evidence(
            state.evidence, file_path=definition.file_path, symbol=definition.name
        )
        best_score = max(
            (float(item.retrieval_metadata.get("score", 0.0) or 0.0) for item in matches),
            default=0.0,
        )
        return (-best_score, definition.file_path, str(definition.id))

    definition = min(exact_definitions, key=definition_order)
    entry_node = _node_from_definition(definition.name, definition, state.evidence)
    state.add_node(entry_node)
    queue = [entry_node.node_id]

    while queue:
        current_id = queue.pop(0)
        if current_id in state.visited_nodes:
            continue
        current = state.nodes[current_id]
        if current.unresolved:
            continue
        references = await cached_execute(
            "find_references",
            FindReferencesInput(repository_id=repository_id, symbol_name=current.symbol),
        )
        if references is None:
            state.partial_reason = "The tool bound stopped further reference inspection."
            break
        state.visited_nodes.add(current_id)
        state.reference_observations[current_id] = [
            {
                "file": item.file,
                "symbol": item.symbol,
                "kind": item.relationship_kind,
            }
            for item in getattr(references, "root", [])
        ]

        pending = sum(
            node_id not in state.visited_nodes and not state.nodes[node_id].unresolved
            for node_id in queue
        )
        if available_tool_calls - calls_used <= pending:
            continue
        related = await cached_execute(
            "get_related_files",
            RelatedFilesInput(
                repository_id=repository_id,
                symbol_name_or_chunk_id=current.symbol,
                include_seed=True,
            ),
        )
        if related is None:
            continue
        related_evidence = list(getattr(related, "root", []))
        state.add_evidence(related_evidence)
        refreshed = _matching_evidence(
            state.evidence, file_path=current.file_path, symbol=current.symbol
        )
        if refreshed:
            current.evidence_ids = list(dict.fromkeys(
                [*current.evidence_ids, *(item.evidence_id for item in refreshed)]
            ))
            current.start_line = refreshed[0].start_line or current.start_line
            current.end_line = refreshed[0].end_line or current.end_line

        raw_edges: list[dict[str, object]] = []
        for item in related_evidence:
            raw_edges.extend(item.relationship_metadata.get("flow_edges", []))
        outgoing: dict[str, dict[str, object]] = {}
        for edge in raw_edges:
            source_id = str(edge.get("source_symbol_id") or "")
            if source_id and source_id != current_id:
                continue
            if not source_id and (
                str(edge.get("source_symbol", "")).lower() != current.symbol.lower()
                or edge.get("source_file") != current.file_path
            ):
                continue
            target = str(edge.get("target_symbol") or "")
            target_file = str(edge.get("target_file") or "")
            target_id = str(edge.get("target_symbol_id") or f"{target_file}:{target}")
            if target and target_file and target_id not in outgoing:
                outgoing[target_id] = edge

        source_evidence = _matching_evidence(
            state.evidence, file_path=current.file_path, symbol=current.symbol
        )
        for target_id, edge in sorted(
            outgoing.items(), key=lambda item: (
                str(item[1].get("target_symbol")), str(item[1].get("target_file")), item[0]
            )
        ):
            target = str(edge["target_symbol"])
            target_file = str(edge["target_file"])
            matches = _matching_evidence(
                state.evidence, file_path=target_file, symbol=target
            )
            raw_symbol_id = edge.get("target_symbol_id")
            symbol_id = uuid.UUID(str(raw_symbol_id)) if raw_symbol_id else None
            state.add_node(
                FlowNode(
                    node_id=target_id,
                    symbol=target,
                    symbol_id=symbol_id,
                    file_path=target_file,
                    start_line=matches[0].start_line if matches else edge.get("target_start_line"),
                    end_line=matches[0].end_line if matches else edge.get("target_end_line"),
                    evidence_ids=[item.evidence_id for item in matches],
                    definition_line=edge.get("target_start_line"),
                )
            )
            state.add_edge(
                FlowEdge(
                    source_id=current_id,
                    target_id=target_id,
                    source_symbol=current.symbol,
                    target_symbol=target,
                    kind=str(edge.get("kind") or "CALLS"),
                    evidence_ids=[item.evidence_id for item in source_evidence],
                    observed_by="get_related_files",
                    confidence=str(edge.get("confidence") or "low"),
                )
            )
            if target_id not in state.visited_nodes and target_id not in queue:
                queue.append(target_id)

        known_targets = {str(edge["target_symbol"]) for edge in outgoing.values()}
        call_sources = [
            item for item in source_evidence
            if item.symbol == current.symbol
            or any(
                contained.get("name") == current.symbol
                for contained in item.relationship_metadata.get("contained_symbols", [])
            )
        ] or source_evidence
        observed_calls: set[str] = set()
        direct_calls: set[str] = set()
        for item in call_sources:
            if item.symbol == current.symbol:
                observed_calls.update(str(call) for call in item.relationship_metadata.get("calls", []))
                direct_calls.update(str(call) for call in item.relationship_metadata.get("direct_calls", []))
            for contained in item.relationship_metadata.get("contained_symbol_calls", []):
                if contained.get("name") == current.symbol and (
                    current.definition_line is None
                    or contained.get("start_line") == current.definition_line
                ):
                    observed_calls.update(str(call) for call in contained.get("calls", []))
                    direct_calls.update(str(call) for call in contained.get("direct_calls", []))
        unresolved_calls = (
            observed_calls - known_targets - {current.symbol}
            if not outgoing else set()
        )
        if unresolved_calls:
            source_text = "\n".join(item.content_excerpt for item in call_sources)
            file_text = "\n".join(
                item.content_excerpt for item in state.evidence
                if item.file_path == current.file_path
            )
            imported_modules = set(
                re.findall(r"(?m)^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", file_text)
            )
            candidates: list[tuple[int, str]] = []
            for call in unresolved_calls:
                if call[:1].isupper() and call.endswith(("Error", "Exception")):
                    continue
                if call in direct_calls:
                    candidates.append((0, call))
                    continue
                receivers = set(re.findall(
                    rf"\b([A-Za-z_][A-Za-z0-9_]*)\.{re.escape(call)}\s*\(",
                    source_text,
                ))
                if receivers & imported_modules:
                    candidates.append((1, call))
            target = next(
                (item for item in explicit_targets if any(item == name for _, name in candidates)),
                min(candidates)[1] if candidates else None,
            )
        else:
            target = None
        if target:
            target_id = f"unresolved:{current_id}:{target}"
            matches = _matching_evidence(
                state.evidence, file_path=current.file_path, symbol=target
            )
            supporting = matches or source_evidence
            state.add_node(
                FlowNode(
                    node_id=target_id,
                    symbol=target,
                    symbol_id=None,
                    file_path=current.file_path,
                    start_line=supporting[0].start_line if supporting else current.start_line,
                    end_line=supporting[0].end_line if supporting else current.end_line,
                    evidence_ids=[item.evidence_id for item in supporting],
                    unresolved=True,
                    definition_line=current.definition_line,
                )
            )
            state.add_edge(
                FlowEdge(
                    source_id=current_id,
                    target_id=target_id,
                    source_symbol=current.symbol,
                    target_symbol=target,
                    kind="CALLS",
                    evidence_ids=[item.evidence_id for item in source_evidence],
                    observed_by="parser_call_metadata",
                    confidence="low",
                )
            )

    return state


def deterministic_flow_trace(
    state: FlowInvestigationState,
    evidence: list[Evidence],
    *,
    partial_reason: str | None = None,
) -> FlowTraceResponse:
    steps: list[FlowStep] = []
    available_evidence = {item.evidence_id: item for item in evidence}
    visible_ids = [
        node_id for node_id in state.ordered_path()
        if state.nodes[node_id].file_path is not None
        and state.nodes[node_id].start_line is not None
        and state.nodes[node_id].end_line is not None
        and any(
            item in available_evidence
            and available_evidence[item].file_path == state.nodes[node_id].file_path
            and available_evidence[item].start_line is not None
            and available_evidence[item].end_line is not None
            for item in state.nodes[node_id].evidence_ids
        )
    ]
    for index, node_id in enumerate(visible_ids):
        node = state.nodes[node_id]
        candidates = [
            available_evidence[item] for item in node.evidence_ids
            if item in available_evidence
            and available_evidence[item].file_path == node.file_path
            and available_evidence[item].start_line is not None
            and available_evidence[item].end_line is not None
        ]
        compatible = [
            item for item in candidates
            if abs(item.start_line - node.start_line) <= 5
            and abs(item.end_line - node.end_line) <= 5
        ]
        start_line, end_line = node.start_line, node.end_line
        if not compatible:
            anchor = candidates[0]
            start_line, end_line = anchor.start_line, anchor.end_line
            compatible = [
                item for item in candidates
                if abs(item.start_line - start_line) <= 5
                and abs(item.end_line - end_line) <= 5
            ]
        evidence_ids = [item.evidence_id for item in compatible]
        next_id = visible_ids[index + 1] if index + 1 < len(visible_ids) else None
        edge = state.edge_between(node_id, next_id) if next_id else None
        unresolved = node.unresolved
        steps.append(
            FlowStep(
                order=len(steps) + 1,
                file=node.file_path,
                symbol=node.symbol,
                start_line=start_line,
                end_line=end_line,
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
    expected_ids = [
        node_id for node_id in state.ordered_path()
        if state.nodes[node_id].file_path is not None
        and state.nodes[node_id].evidence_ids
    ]
    if [
        (step["file"], step["symbol"])
        for step in data["steps"]
    ] != [
        (state.nodes[node_id].file_path, state.nodes[node_id].symbol)
        for node_id in expected_ids
    ]:
        return deterministic_flow_trace(state, evidence)
    if any(not step["evidence_ids"] for step in data["steps"]):
        return deterministic_flow_trace(state, evidence)
    for index, step in enumerate(data["steps"]):
        node_id = expected_ids[index]
        next_id = expected_ids[index + 1] if index + 1 < len(expected_ids) else None
        edge = state.edge_between(node_id, next_id) if next_id else None
        node = state.nodes[node_id]
        if next_id is None:
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
