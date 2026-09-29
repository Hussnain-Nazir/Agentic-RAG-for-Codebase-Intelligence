import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUp, GitCompare, Layers, MapPin, MessageSquareText, Milestone, Save, Trash2, Waypoints,
} from "lucide-react";

import { useAnalysis, useSaveFinding } from "../../api/hooks";
import { authToken } from "../../api/client";
import { clearConversation as clearStoredConversation, conversationKey, readConversation, writeConversation } from "../../api/conversations";
import type {
  ArchitectureResponse, ChangeImpactResponse, Evidence, FlowTraceResponse,
  ModelComparisonResponse, ModelSlot, RepositoryAnswer,
} from "../../api/types";
import { PrismLogo } from "../common/PrismLogo";
import { ErrorNotice } from "../common/Shell";
import { externalSource } from "./externalSource";

export type AnalysisMode = "ask" | "flow" | "impact" | "architecture";
export type AnalysisView =
  | { mode: "ask"; data: RepositoryAnswer; runId: string }
  | { mode: "flow"; data: FlowTraceResponse; runId: string }
  | { mode: "impact"; data: ChangeImpactResponse; runId: string }
  | { mode: "architecture"; data: ArchitectureResponse; runId: string }
  | { mode: "compare"; data: ModelComparisonResponse; runId: string };

interface Turn {
  id: number;
  question: string;
  mode: AnalysisMode;
  view: AnalysisView | null;
  error: string | null;
  pending: boolean;
}

function isStoredView(value: unknown): value is AnalysisView {
  if (!value || typeof value !== "object") return false;
  const view = value as { mode?: unknown; runId?: unknown; data?: unknown };
  if (typeof view.runId !== "string" || !view.data || typeof view.data !== "object") return false;
  const data = view.data as Record<string, unknown>;
  switch (view.mode) {
    case "ask": return typeof data.answer === "string" && Array.isArray(data.evidence);
    case "flow": return typeof data.summary === "string" && Array.isArray(data.steps) && Array.isArray(data.evidence);
    case "impact": return typeof data.requested_change === "string" && Array.isArray(data.directly_affected) && Array.isArray(data.likely_indirectly_affected) && Array.isArray(data.evidence);
    case "architecture": return typeof data.summary === "string" && Array.isArray(data.evidence) && Array.isArray(data.main_folders);
    case "compare": return typeof data.question === "string" && Array.isArray(data.results);
    default: return false;
  }
}

function restoredTurns(key: string | null): Turn[] {
  const modes: AnalysisMode[] = ["ask", "flow", "impact", "architecture"];
  return readConversation<unknown>(key).filter((value): value is Turn => {
    if (!value || typeof value !== "object") return false;
    const turn = value as Partial<Turn>;
    return typeof turn.id === "number" && typeof turn.question === "string"
      && modes.includes(turn.mode as AnalysisMode)
      && typeof turn.pending === "boolean"
      && (turn.error === null || typeof turn.error === "string")
      && (turn.view === null || isStoredView(turn.view));
  }).map((turn) => turn.pending ? { ...turn, pending: false, error: "The request was interrupted by a page reload." } : turn);
}

export function evidenceForView(view: AnalysisView | null): Evidence[] {
  if (!view) return [];
  if (view.mode !== "compare") return view.data.evidence;
  const unique = new Map<string, Evidence>();
  view.data.results.forEach((result) => result.response?.evidence.forEach((item) => unique.set(item.evidence_id, item)));
  return [...unique.values()];
}

function durableEvidenceIds(evidence: Evidence[]): string[] {
  const ids = new Set<string>();
  evidence.filter((item) => item.source_type === "CODE").forEach((item) => {
    const sourceIds = item.retrieval_metadata.source_chunk_ids;
    if (Array.isArray(sourceIds) && sourceIds.length > 0) {
      sourceIds.filter((id): id is string => typeof id === "string").forEach((id) => ids.add(id));
    } else ids.add(item.evidence_id);
  });
  return [...ids];
}

function CitationIds({ ids }: { ids: string[] }) {
  return ids.length ? <span className="font-mono text-xs text-accent-hover">Evidence: {ids.map((id) => id.slice(0, 8)).join(", ")}</span> : null;
}

function EvidenceChips({ evidence, onOpen }: { evidence: Evidence[]; onOpen?: (evidence: Evidence) => void }) {
  if (evidence.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {evidence.map((item) => {
        const external = externalSource(item);
        return <button
          key={item.evidence_id}
          type="button"
          disabled={!onOpen}
          onClick={() => onOpen?.(item)}
          className="inline-flex items-center gap-1 rounded-full border border-border-strong bg-surface-3 px-2.5 py-1 font-mono text-[11px] text-accent-hover transition-colors duration-150 hover:border-accent-muted disabled:cursor-default disabled:opacity-80"
        >
          {!external && <MapPin size={10} strokeWidth={2} />}
          {external ? `External: ${external.title}${external.urlText ? ` · ${external.urlText}` : ""}`
            : item.file_path ? `${item.file_path}:${item.start_line ?? "?"}-${item.end_line ?? "?"}` : item.source_type}
        </button>;
      })}
    </div>
  );
}

const confidenceStyle: Record<string, string> = {
  high: "text-success", medium: "text-warning", low: "text-ink-muted",
};

function ResultContent({ view, onOpenEvidence }: { view: AnalysisView; onOpenEvidence?: (evidence: Evidence) => void }) {
  if (view.mode === "ask") return (
    <div>
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink-primary">{view.data.answer}</p>
      <p className={`mt-3 text-sm font-medium ${confidenceStyle[view.data.confidence]}`}>Confidence: {view.data.confidence}</p>
      {view.data.limitations && <p className="mt-2 text-sm text-warning">Limitations: {view.data.limitations}</p>}
      <EvidenceChips evidence={view.data.evidence} onOpen={onOpenEvidence} />
    </div>
  );

  if (view.mode === "flow") return (
    <div>
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink-primary">{view.data.summary}</p>
      {view.data.steps.length === 0 && <p className="mt-4 text-sm text-ink-secondary">No flow steps were established.</p>}
      <ol className="relative mt-5 space-y-3">
        {[...view.data.steps].sort((a, b) => a.order - b.order).map((step, index, all) => {
          const stepEvidence = view.data.evidence.filter((item) => step.evidence_ids.includes(item.evidence_id));
          return (
            <li key={`${step.order}-${step.file}-${step.symbol}`} className="relative rounded-lg border border-border-subtle bg-surface-1 p-4 pl-5">
              {index < all.length - 1 && <span aria-hidden className="absolute -bottom-3 left-[1.65rem] h-3 w-px bg-border-strong" />}
              <div className="flex items-center gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[11px] font-semibold text-accent-hover">{step.order}</span>
                <h3 className="font-medium text-ink-primary">{step.order}. {step.symbol}</h3>
              </div>
              <p className="mt-1.5 break-all font-mono text-xs text-ink-muted">{step.file}:{step.start_line}-{step.end_line}</p>
              <p className="mt-2 text-sm text-ink-secondary">{step.explanation}</p>
              <p className="mt-2 text-xs text-ink-muted">
                {step.unresolved ? "Unresolved transition" : step.relationship_to_next ? `Next: ${step.relationship_to_next}` : "Final step"}
              </p>
              <div className="mt-2 flex items-center gap-2"><CitationIds ids={step.evidence_ids} /></div>
              <EvidenceChips evidence={stepEvidence} onOpen={onOpenEvidence} />
            </li>
          );
        })}
      </ol>
    </div>
  );

  if (view.mode === "impact") return (
    <div>
      <p className="mb-5 text-[15px] text-ink-primary">Requested change: {view.data.requested_change}</p>
      {(["directly_affected", "likely_indirectly_affected"] as const).map((key) => (
        <section key={key} className="mt-5">
          <h3 className="text-sm font-medium uppercase tracking-wide text-ink-secondary">
            {key === "directly_affected" ? "Directly affected" : "Likely indirectly affected"}
          </h3>
          {view.data[key].length === 0 && <p className="mt-2 text-sm text-ink-muted">No items identified.</p>}
          <ul className="mt-3 space-y-3">
            {view.data[key].map((item, index) => {
              const itemEvidence = view.data.evidence.filter((entry) => item.evidence_ids.includes(entry.evidence_id));
              return (
                <li key={`${item.file}-${item.symbol}-${index}`} className="rounded-lg border border-border-subtle bg-surface-1 p-4">
                  <p className="font-medium text-ink-primary">{item.symbol} <span className={`text-xs font-normal ${confidenceStyle[item.confidence]}`}>({item.confidence})</span></p>
                  <p className="break-all font-mono text-xs text-ink-muted">{item.file}</p>
                  <p className="mt-2 text-sm text-ink-secondary">{item.reason}</p>
                  <p className="mt-2 text-sm text-ink-secondary">Action: {item.recommended_action}</p>
                  {!!item.tests_to_inspect.length && <p className="mt-1 text-xs text-ink-muted">Tests: {item.tests_to_inspect.join(", ")}</p>}
                  <div className="mt-2"><CitationIds ids={item.evidence_ids} /></div>
                  <EvidenceChips evidence={itemEvidence} onOpen={onOpenEvidence} />
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );

  if (view.mode === "architecture") {
    const fields: [string, string][] = [
      ["Languages", Object.entries(view.data.languages).map(([name, count]) => `${name}: ${count}`).join(", ") || "None"],
      ["Main folders", view.data.main_folders.join(", ") || "None"],
      ["Frameworks", view.data.frameworks_detected.join(", ") || "None"],
      ["Entrypoints", view.data.entrypoints.join(", ") || "None"],
      ["Backend boundary", view.data.backend_boundary ?? "Unknown"],
      ["Frontend boundary", view.data.frontend_boundary ?? "Unknown"],
      ["Database layer", view.data.database_layer ?? "Unknown"],
      ["API organization", view.data.api_organization ?? "Unknown"],
      ["Auth locations", view.data.auth_locations.join(", ") || "None"],
      ["Test locations", view.data.test_locations.join(", ") || "None"],
    ];
    return (
      <div>
        <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink-primary">{view.data.summary}</p>
        <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([label, value]) => (
            <div key={label} className="rounded-md border border-border-subtle bg-surface-1 p-3">
              <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
              <dd className="mt-1 break-words text-ink-primary">{value}</dd>
            </div>
          ))}
        </dl>
        <EvidenceChips evidence={view.data.evidence} onOpen={onOpenEvidence} />
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {view.data.results.map((result) => (
        <article key={result.slot} className="rounded-lg border border-border-subtle bg-surface-1 p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-primary">Model {result.slot}</h3>
            <span className="badge">{result.validation_status}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-ink-muted">{result.model_name}</p>
          {result.error && <p className="mt-4 text-sm text-danger">{result.error}</p>}
          {result.response && <p className="mt-4 whitespace-pre-wrap text-sm text-ink-primary">{result.response.answer}</p>}
          {result.response?.limitations && <p className="mt-3 text-sm text-warning">{result.response.limitations}</p>}
          <EvidenceChips evidence={result.response?.evidence ?? []} onOpen={onOpenEvidence} />
          <footer className="mt-5 border-t border-border-subtle pt-3 text-xs text-ink-muted">
            {result.latency_ms} ms · {result.input_tokens ?? "?"} input tokens · {result.output_tokens ?? "?"} output tokens · {result.validation_status}
            {result.citation_total != null && <p className="mt-1">Citations: {result.citation_accepted} accepted, {result.citation_rejected} rejected of {result.citation_total}</p>}
            {Object.entries(result.citation_rejection_reasons ?? {}).map(([reason, count]) => (
              <p key={reason} className="mt-1 text-warning">{reason}: {count}</p>
            ))}
          </footer>
        </article>
      ))}
    </div>
  );
}

const tabs: { mode: AnalysisMode; label: string; icon: typeof MessageSquareText }[] = [
  { mode: "ask", label: "Codebase Q&A", icon: MessageSquareText },
  { mode: "flow", label: "Flow Trace", icon: Waypoints },
  { mode: "impact", label: "Change Impact", icon: Milestone },
  { mode: "architecture", label: "Architecture", icon: Layers },
];

export function AnalysisWorkspace({ repositoryId, modelSlot, mode, onModeChange, view, onResult, onOpenEvidence, composerLeft, onClear }: {
  repositoryId: string; modelSlot: ModelSlot; mode: AnalysisMode;
  onModeChange: (mode: AnalysisMode) => void; view: AnalysisView | null;
  onResult: (view: AnalysisView | null) => void;
  onOpenEvidence?: (evidence: Evidence) => void;
  composerLeft?: ReactNode;
  onClear?: () => void;
}) {
  const [question, setQuestion] = useState("");
  const storageKey = conversationKey(authToken.get(), repositoryId);
  const [history, setHistory] = useState<Turn[]>(() => restoredTurns(storageKey));
  const [storageWarning, setStorageWarning] = useState(false);
  const requestVersion = useRef(0);
  const nextTurnId = useRef(Math.max(0, ...history.map((turn) => turn.id)));
  const analysis = useAnalysis(repositoryId);
  const save = useSaveFinding(repositoryId);
  const canSave = view?.mode === "flow" || view?.mode === "impact";
  const evidenceIds = canSave ? durableEvidenceIds(evidenceForView(view)) : [];

  useEffect(() => {
    setStorageWarning(!writeConversation(storageKey, history));
  }, [storageKey, history]);

  useEffect(() => {
    const latestView = [...history].reverse().find((turn) => turn.view)?.view;
    if (latestView) onResult(latestView);
  }, []);

  async function submit(kind: "ask" | "compare") {
    if (mode !== "architecture" && !question.trim()) return;
    const version = ++requestVersion.current;
    const askedQuestion = question.trim();
    const turnId = ++nextTurnId.current;
    setQuestion("");
    setHistory((previous) => [...previous, { id: turnId, question: askedQuestion, mode, view: null, error: null, pending: true }]);
    onResult(null);
    save.reset();
    try {
      const response = await analysis.mutateAsync({ type: kind === "compare" ? "compare" : mode, question: askedQuestion, modelSlot });
      if (version !== requestVersion.current) return;
      let next: AnalysisView;
      if ("answer" in response) next = { mode: "ask", data: response.answer, runId: response.agent_run_id };
      else if ("trace" in response) next = { mode: "flow", data: response.trace, runId: response.agent_run_id };
      else if ("impact" in response) next = { mode: "impact", data: response.impact, runId: response.agent_run_id };
      else if ("results" in response) next = { mode: "compare", data: response, runId: response.agent_run_id };
      else next = { mode: "architecture", data: response, runId: response.agent_run_id };
      onResult(next);
      setHistory((previous) => previous.map((turn) => turn.id === turnId ? { ...turn, view: next, pending: false } : turn));
    } catch (error) {
      if (version !== requestVersion.current) return;
      const message = error instanceof Error ? error.message : "Analysis unavailable";
      setHistory((previous) => previous.map((turn) => turn.id === turnId ? { ...turn, error: message, pending: false } : turn));
    }
  }

  async function saveFinding() {
    if (!view || (view.mode !== "flow" && view.mode !== "impact") || evidenceIds.length === 0) return;
    const type = view.mode === "flow" ? "FLOW_TRACE" : "IMPACT";
    const lastQuestion = history[history.length - 1]?.question ?? "";
    const title = view.mode === "flow" ? `Flow trace: ${lastQuestion}` : `Impact: ${lastQuestion}`;
    try { await save.mutateAsync({ type, content: { ...view.data, title }, evidenceIds }); }
    catch { /* Save error is shown below. */ }
  }

  function clearConversation() {
    requestVersion.current += 1;
    analysis.reset();
    save.reset();
    setHistory([]);
    clearStoredConversation(storageKey);
    setStorageWarning(false);
    setQuestion("");
    onResult(null);
    onClear?.();
  }

  const modeLabel = tabs.find((tab) => tab.mode === mode)?.label ?? "Codebase Q&A";

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div role="tablist" aria-label="Analysis type" className="flex shrink-0 flex-wrap gap-1 border-b border-border-subtle px-1 pb-3">
        {tabs.map((tab) => (
          <button
            key={tab.mode}
            role="tab"
            aria-selected={mode === tab.mode}
            type="button"
            className="tab-trigger"
            onClick={() => onModeChange(tab.mode)}
          >
            <tab.icon size={14} strokeWidth={1.75} /> {tab.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-1 py-6">
          {history.length === 0 && !analysis.isPending && !analysis.isError && (
            <div className="flex flex-col items-center px-4 py-16 text-center">
              <MessageSquareText size={22} strokeWidth={1.5} className="mb-4 text-ink-disabled" />
              <p className="text-[15px] font-medium text-ink-secondary">Ask anything about this repository.</p>
              <p className="mt-1.5 text-sm text-ink-muted">{modeLabel} uses the current index and cites the code it relies on.</p>
            </div>
          )}

          <div className="space-y-10">
            {history.map((turn) => (
              <div key={turn.id} data-testid="conversation-turn" className="min-w-0 space-y-5 animate-fade-in">
                <div className="flex justify-end">
                  <div className="flex min-w-0 max-w-[85%] flex-col items-end gap-1.5 sm:max-w-[75%]">
                    <span className="text-xs font-medium text-ink-muted">You</span>
                    <p className="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere] rounded-xl rounded-br-sm bg-accent px-4 py-3 text-sm leading-relaxed text-white shadow-panel">
                      {turn.mode === "architecture" ? "Explain architecture" : turn.question}
                    </p>
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-ink-secondary">
                    <PrismLogo size={24} className="shrink-0" />
                    PRISM
                  </div>
                  <div className="min-w-0 border-l border-border-subtle pl-4 sm:pl-5">
                    {turn.pending && <div className="flex items-center gap-2 text-sm text-ink-secondary"><span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />Gathering evidence and validating the result...</div>}
                    {turn.error && <ErrorNotice message={turn.error} />}
                    {turn.view && <ResultContent view={turn.view} onOpenEvidence={onOpenEvidence} />}
                    {turn.view && canSave && turn === history[history.length - 1] && (
                      <div className="mt-4 border-t border-border-subtle pt-4">
                        <button type="button" className="button-secondary" disabled={save.isPending || save.isSuccess || evidenceIds.length === 0} onClick={() => void saveFinding()}>
                          <Save size={14} strokeWidth={1.75} />
                          {save.isSuccess ? "Finding saved" : save.isPending ? "Saving..." : "Save Finding"}
                        </button>
                        {evidenceIds.length === 0 && <p className="mt-2 text-xs text-ink-muted">Saving requires current code evidence.</p>}
                        {save.isError && <div className="mt-3"><ErrorNotice message={save.error.message} /></div>}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
          {storageWarning && <p role="status" className="mt-4 text-xs text-warning">This conversation is too large to save in this tab. It remains visible until you leave the page.</p>}

        </div>
      </div>

      <div className="shrink-0 border-t border-border-subtle pt-3">
        {mode !== "architecture" && (
          <label className="sr-only" htmlFor="analysis-question">{mode === "impact" ? "Describe the proposed change" : "Question"}</label>
        )}
        {mode !== "architecture" && (
          <textarea
            id="analysis-question"
            className="input min-h-16 resize-y border-none bg-surface-1 focus:ring-0"
            placeholder={mode === "impact" ? "Describe the proposed change..." : "Ask about this repository..."}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        )}
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0">{composerLeft}</div>
            <button type="button" className="button-ghost shrink-0" aria-label="Clear Conversation" disabled={history.length === 0 && !question.trim() && !analysis.isPending && !analysis.isError} onClick={clearConversation}>
              <Trash2 size={14} strokeWidth={1.75} /> Clear Conversation
            </button>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" className="button-primary" disabled={analysis.isPending || (mode !== "architecture" && !question.trim())} onClick={() => void submit("ask")}>
              {analysis.isPending ? "Investigating..." : mode === "architecture" ? "Explain architecture" : "Ask"}
              {mode !== "architecture" && <ArrowUp size={15} strokeWidth={2} />}
            </button>
            {mode === "ask" && (
              <button type="button" className="button-secondary" disabled={analysis.isPending || !question.trim()} onClick={() => void submit("compare")}>
                <GitCompare size={14} strokeWidth={1.75} /> Ask &amp; Compare
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
