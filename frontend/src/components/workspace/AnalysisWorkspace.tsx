import { useEffect, useRef, useState } from "react";
import {
  ArrowRight, GitCompare, Layers, MessageSquareText, Milestone, Save, Waypoints,
} from "lucide-react";

import { useAnalysis, useSaveFinding } from "../../api/hooks";
import type {
  ArchitectureResponse, ChangeImpactResponse, Evidence, FlowTraceResponse,
  ModelComparisonResponse, ModelSlot, RepositoryAnswer,
} from "../../api/types";
import { ErrorNotice } from "../common/Shell";
import { EmptyState } from "../common/EmptyState";

export type AnalysisMode = "ask" | "flow" | "impact" | "architecture" | "compare";
export type AnalysisView =
  | { mode: "ask"; data: RepositoryAnswer; runId: string }
  | { mode: "flow"; data: FlowTraceResponse; runId: string }
  | { mode: "impact"; data: ChangeImpactResponse; runId: string }
  | { mode: "architecture"; data: ArchitectureResponse; runId: string }
  | { mode: "compare"; data: ModelComparisonResponse; runId: string };

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

const confidenceStyle: Record<string, string> = {
  high: "text-success", medium: "text-warning", low: "text-ink-muted",
};

function ResultContent({ view }: { view: AnalysisView }) {
  if (view.mode === "ask") return (
    <div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-primary">{view.data.answer}</p>
      <p className={`mt-4 text-sm font-medium ${confidenceStyle[view.data.confidence]}`}>Confidence: {view.data.confidence}</p>
      {view.data.limitations && <p className="mt-2 text-sm text-warning">Limitations: {view.data.limitations}</p>}
    </div>
  );

  if (view.mode === "flow") return (
    <div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-primary">{view.data.summary}</p>
      {view.data.steps.length === 0 && <p className="mt-4 text-sm text-ink-secondary">No flow steps were established.</p>}
      <ol className="relative mt-5 space-y-3">
        {[...view.data.steps].sort((a, b) => a.order - b.order).map((step, index, all) => (
          <li key={`${step.order}-${step.file}-${step.symbol}`} className="relative rounded-lg border border-border bg-surface-1 p-4 pl-5">
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
            <div className="mt-2"><CitationIds ids={step.evidence_ids} /></div>
          </li>
        ))}
      </ol>
    </div>
  );

  if (view.mode === "impact") return (
    <div>
      <p className="mb-5 text-sm text-ink-primary">Requested change: {view.data.requested_change}</p>
      {(["directly_affected", "likely_indirectly_affected"] as const).map((key) => (
        <section key={key} className="mt-5">
          <h3 className="text-sm font-medium uppercase tracking-wide text-ink-secondary">
            {key === "directly_affected" ? "Directly affected" : "Likely indirectly affected"}
          </h3>
          {view.data[key].length === 0 && <p className="mt-2 text-sm text-ink-muted">No items identified.</p>}
          <ul className="mt-3 space-y-3">
            {view.data[key].map((item, index) => (
              <li key={`${item.file}-${item.symbol}-${index}`} className="rounded-lg border border-border bg-surface-1 p-4">
                <p className="font-medium text-ink-primary">{item.symbol} <span className={`text-xs font-normal ${confidenceStyle[item.confidence]}`}>({item.confidence})</span></p>
                <p className="break-all font-mono text-xs text-ink-muted">{item.file}</p>
                <p className="mt-2 text-sm text-ink-secondary">{item.reason}</p>
                <p className="mt-2 text-sm text-ink-secondary">Action: {item.recommended_action}</p>
                {!!item.tests_to_inspect.length && <p className="mt-1 text-xs text-ink-muted">Tests: {item.tests_to_inspect.join(", ")}</p>}
                <div className="mt-2"><CitationIds ids={item.evidence_ids} /></div>
              </li>
            ))}
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
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-primary">{view.data.summary}</p>
        <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([label, value]) => (
            <div key={label} className="rounded-md border border-border-subtle bg-surface-1 p-3">
              <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
              <dd className="mt-1 break-words text-ink-primary">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {view.data.results.map((result) => (
        <article key={result.slot} className="rounded-lg border border-border bg-surface-1 p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-primary">Model {result.slot}</h3>
            <span className="badge">{result.validation_status}</span>
          </div>
          <p className="mt-1 font-mono text-xs text-ink-muted">{result.model_name}</p>
          {result.error && <p className="mt-4 text-sm text-danger">{result.error}</p>}
          {result.response && <p className="mt-4 whitespace-pre-wrap text-sm text-ink-primary">{result.response.answer}</p>}
          {result.response?.limitations && <p className="mt-3 text-sm text-warning">{result.response.limitations}</p>}
          <footer className="mt-5 border-t border-border-subtle pt-3 text-xs text-ink-muted">
            {result.latency_ms} ms · {result.input_tokens ?? "?"} input tokens · {result.output_tokens ?? "?"} output tokens · {result.validation_status}
          </footer>
        </article>
      ))}
    </div>
  );
}

const tabs: { mode: AnalysisMode; label: string; icon: typeof MessageSquareText }[] = [
  { mode: "ask", label: "Ask", icon: MessageSquareText },
  { mode: "flow", label: "Flow Trace", icon: Waypoints },
  { mode: "impact", label: "Change Impact", icon: Milestone },
  { mode: "architecture", label: "Architecture", icon: Layers },
];

export function AnalysisWorkspace({ repositoryId, modelSlot, mode, onModeChange, view, onResult }: {
  repositoryId: string; modelSlot: ModelSlot; mode: AnalysisMode;
  onModeChange: (mode: AnalysisMode) => void; view: AnalysisView | null;
  onResult: (view: AnalysisView | null) => void;
}) {
  const [question, setQuestion] = useState("");
  const requestVersion = useRef(0);
  const analysis = useAnalysis(repositoryId);
  const save = useSaveFinding(repositoryId);
  const canSave = view?.mode === "flow" || view?.mode === "impact";
  const evidenceIds = canSave ? durableEvidenceIds(evidenceForView(view)) : [];

  useEffect(() => {
    requestVersion.current += 1;
    analysis.reset();
    save.reset();
  }, [mode]);

  async function submit() {
    if (mode !== "architecture" && !question.trim()) return;
    const version = ++requestVersion.current;
    onResult(null);
    save.reset();
    try {
      const response = await analysis.mutateAsync({ type: mode, question: question.trim(), modelSlot });
      if (version !== requestVersion.current) return;
      if ("answer" in response) onResult({ mode: "ask", data: response.answer, runId: response.agent_run_id });
      else if ("trace" in response) onResult({ mode: "flow", data: response.trace, runId: response.agent_run_id });
      else if ("impact" in response) onResult({ mode: "impact", data: response.impact, runId: response.agent_run_id });
      else if ("results" in response) onResult({ mode: "compare", data: response, runId: response.agent_run_id });
      else onResult({ mode: "architecture", data: response, runId: response.agent_run_id });
    } catch { /* The mutation error is shown in this panel. */ }
  }

  async function saveFinding() {
    if (!view || (view.mode !== "flow" && view.mode !== "impact") || evidenceIds.length === 0) return;
    const type = view.mode === "flow" ? "FLOW_TRACE" : "IMPACT";
    const title = view.mode === "flow" ? `Flow trace: ${question}` : `Impact: ${question}`;
    try { await save.mutateAsync({ type, content: { ...view.data, title }, evidenceIds }); }
    catch { /* Save error is shown below. */ }
  }

  return (
    <section aria-label="Analysis workspace" className="panel flex min-w-0 flex-col">
      <div className="panel-header">
        <h2 className="text-sm font-medium text-ink-primary">Analysis Workspace</h2>
        {mode === "compare" && <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted"><GitCompare size={13} strokeWidth={1.75} /> Model A vs Model B</span>}
      </div>

      <div className="panel-body pb-0">
        <div role="tablist" aria-label="Analysis type" className="flex flex-wrap gap-1 rounded-md bg-surface-1 p-1">
          {tabs.map((tab) => (
            <button
              key={tab.mode}
              role="tab"
              aria-selected={mode === tab.mode}
              type="button"
              className="tab-trigger"
              onClick={() => { onModeChange(tab.mode); onResult(null); }}
            >
              <tab.icon size={14} strokeWidth={1.75} /> {tab.label}
            </button>
          ))}
        </div>

        {mode === "compare" && <p className="mt-4 text-sm text-ink-secondary">Compare Models uses the same question and evidence for both slots.</p>}

        {mode !== "architecture" && (
          <div className="mt-4">
            <label className="label" htmlFor="analysis-question">{mode === "impact" ? "Describe the proposed change" : "Question"}</label>
            <textarea id="analysis-question" className="input min-h-24 resize-y" value={question} onChange={(event) => setQuestion(event.target.value)} />
          </div>
        )}

        <div className="mt-4 flex items-center gap-3 pb-4">
          <button type="button" className="button-primary" disabled={analysis.isPending || (mode !== "architecture" && !question.trim())} onClick={() => void submit()}>
            {analysis.isPending ? "Investigating..." : (
              <>
                {mode === "architecture" ? "Explain architecture" : mode === "compare" ? "Compare Models" : "Run analysis"}
                <ArrowRight size={15} strokeWidth={2} />
              </>
            )}
          </button>
        </div>
      </div>

      <div className="border-t border-border-subtle p-4">
        {analysis.isPending && (
          <div className="flex items-center gap-2 text-sm text-ink-secondary">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />
            Gathering evidence and validating the result...
          </div>
        )}
        {analysis.isError && <ErrorNotice message={analysis.error.message} onRetry={() => void submit()} />}
        {!view && !analysis.isPending && !analysis.isError && <EmptyState title="Ask a question to get started." />}
        {view && (
          <div className="animate-fade-in">
            <ResultContent view={view} />
            {canSave && (
              <div className="mt-6 border-t border-border-subtle pt-4">
                <button type="button" className="button-secondary" disabled={save.isPending || save.isSuccess || evidenceIds.length === 0} onClick={() => void saveFinding()}>
                  <Save size={14} strokeWidth={1.75} />
                  {save.isSuccess ? "Finding saved" : save.isPending ? "Saving..." : "Save Finding"}
                </button>
                {evidenceIds.length === 0 && <p className="mt-2 text-xs text-ink-muted">Saving requires current code evidence.</p>}
                {save.isError && <div className="mt-3"><ErrorNotice message={save.error.message} /></div>}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
