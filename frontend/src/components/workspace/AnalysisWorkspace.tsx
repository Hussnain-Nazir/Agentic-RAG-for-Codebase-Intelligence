import { useEffect, useRef, useState } from "react";

import { useAnalysis, useSaveFinding } from "../../api/hooks";
import type {
  ArchitectureResponse, ChangeImpactResponse, Evidence, FlowTraceResponse,
  ModelComparisonResponse, ModelSlot, RepositoryAnswer,
} from "../../api/types";
import { ErrorNotice } from "../common/Shell";

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
  return ids.length ? <span className="text-xs text-cyan-300">Evidence: {ids.map((id) => id.slice(0, 8)).join(", ")}</span> : null;
}

function ResultContent({ view }: { view: AnalysisView }) {
  if (view.mode === "ask") return <div>
    <p className="whitespace-pre-wrap">{view.data.answer}</p>
    <p className="mt-3 text-sm text-slate-400">Confidence: {view.data.confidence}</p>
    {view.data.limitations && <p className="mt-2 text-sm text-amber-300">Limitations: {view.data.limitations}</p>}
  </div>;
  if (view.mode === "flow") return <div>
    <p className="whitespace-pre-wrap">{view.data.summary}</p>
    {view.data.steps.length === 0 && <p className="mt-4 text-slate-400">No flow steps were established.</p>}
    <ol className="mt-5 space-y-3">{[...view.data.steps].sort((a, b) => a.order - b.order).map((step) => <li key={`${step.order}-${step.file}-${step.symbol}`} className="rounded-lg border border-slate-700 p-4">
      <h3 className="font-medium">{step.order}. {step.symbol}</h3>
      <p className="mt-1 break-all text-xs text-slate-400">{step.file}:{step.start_line}-{step.end_line}</p>
      <p className="mt-2 text-sm">{step.explanation}</p>
      <p className="mt-2 text-xs text-slate-400">{step.unresolved ? "Unresolved transition" : step.relationship_to_next ? `Next: ${step.relationship_to_next}` : "Final step"}</p>
      <CitationIds ids={step.evidence_ids} />
    </li>)}</ol>
  </div>;
  if (view.mode === "impact") return <div>
    <p className="mb-5">Requested change: {view.data.requested_change}</p>
    {(["directly_affected", "likely_indirectly_affected"] as const).map((key) => <section key={key} className="mt-5">
      <h3 className="text-lg font-semibold">{key === "directly_affected" ? "Directly affected" : "Likely indirectly affected"}</h3>
      {view.data[key].length === 0 && <p className="mt-2 text-sm text-slate-400">No items identified.</p>}
      <ul className="mt-3 space-y-3">{view.data[key].map((item, index) => <li key={`${item.file}-${item.symbol}-${index}`} className="rounded-lg border border-slate-700 p-4">
        <p className="font-medium">{item.symbol} <span className="text-xs text-slate-400">({item.confidence})</span></p>
        <p className="break-all text-xs text-slate-400">{item.file}</p>
        <p className="mt-2 text-sm">{item.reason}</p>
        <p className="mt-2 text-sm">Action: {item.recommended_action}</p>
        {!!item.tests_to_inspect.length && <p className="mt-1 text-xs text-slate-400">Tests: {item.tests_to_inspect.join(", ")}</p>}
        <CitationIds ids={item.evidence_ids} />
      </li>)}</ul>
    </section>)}
  </div>;
  if (view.mode === "architecture") return <div>
    <p className="whitespace-pre-wrap">{view.data.summary}</p>
    <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
      <div><dt className="text-slate-400">Languages</dt><dd>{Object.entries(view.data.languages).map(([name, count]) => `${name}: ${count}`).join(", ") || "None"}</dd></div>
      <div><dt className="text-slate-400">Main folders</dt><dd>{view.data.main_folders.join(", ") || "None"}</dd></div>
      <div><dt className="text-slate-400">Frameworks</dt><dd>{view.data.frameworks_detected.join(", ") || "None"}</dd></div>
      <div><dt className="text-slate-400">Entrypoints</dt><dd>{view.data.entrypoints.join(", ") || "None"}</dd></div>
      <div><dt className="text-slate-400">Backend boundary</dt><dd>{view.data.backend_boundary ?? "Unknown"}</dd></div>
      <div><dt className="text-slate-400">Frontend boundary</dt><dd>{view.data.frontend_boundary ?? "Unknown"}</dd></div>
      <div><dt className="text-slate-400">Database layer</dt><dd>{view.data.database_layer ?? "Unknown"}</dd></div>
      <div><dt className="text-slate-400">API organization</dt><dd>{view.data.api_organization ?? "Unknown"}</dd></div>
      <div><dt className="text-slate-400">Auth locations</dt><dd>{view.data.auth_locations.join(", ") || "None"}</dd></div>
      <div><dt className="text-slate-400">Test locations</dt><dd>{view.data.test_locations.join(", ") || "None"}</dd></div>
    </dl>
  </div>;
  return <div className="grid gap-4 lg:grid-cols-2">
    {view.data.results.map((result) => <article key={result.slot} className="rounded-lg border border-slate-700 p-4">
      <h3 className="text-lg font-semibold">Model {result.slot}</h3>
      <p className="text-sm text-slate-400">{result.model_name}</p>
      {result.error && <p className="mt-4 text-rose-300">{result.error}</p>}
      {result.response && <p className="mt-4 whitespace-pre-wrap">{result.response.answer}</p>}
      {result.response?.limitations && <p className="mt-3 text-sm text-amber-300">{result.response.limitations}</p>}
      <footer className="mt-5 border-t border-slate-700 pt-3 text-xs text-slate-400">
        {result.latency_ms} ms · {result.input_tokens ?? "?"} input tokens · {result.output_tokens ?? "?"} output tokens · {result.validation_status}
      </footer>
    </article>)}
  </div>;
}

const tabs: { mode: AnalysisMode; label: string }[] = [
  { mode: "ask", label: "Ask" }, { mode: "flow", label: "Flow Trace" },
  { mode: "impact", label: "Change Impact" }, { mode: "architecture", label: "Architecture" },
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

  return <section aria-label="Analysis workspace" className="panel min-w-0">
    <h2 className="text-lg font-semibold">Analysis Workspace</h2>
    <div role="tablist" aria-label="Analysis type" className="mt-4 flex flex-wrap gap-2">{tabs.map((tab) => <button key={tab.mode} role="tab" aria-selected={mode === tab.mode} type="button" className={mode === tab.mode ? "button-primary text-sm" : "rounded-lg border border-slate-700 px-3 py-2 text-sm"} onClick={() => { onModeChange(tab.mode); onResult(null); }}>
      {tab.label}
    </button>)}</div>
    {mode === "compare" && <p className="mt-4 text-sm text-slate-400">Compare Models uses the same question and evidence for both slots.</p>}
    {mode !== "architecture" && <div className="mt-5"><label className="label" htmlFor="analysis-question">{mode === "impact" ? "Describe the proposed change" : "Question"}</label>
      <textarea id="analysis-question" className="input min-h-28" value={question} onChange={(event) => setQuestion(event.target.value)} /></div>}
    <button type="button" className="button-primary mt-4" disabled={analysis.isPending || (mode !== "architecture" && !question.trim())} onClick={() => void submit()}>
      {analysis.isPending ? "Investigating..." : mode === "architecture" ? "Explain architecture" : mode === "compare" ? "Compare Models" : "Run analysis"}
    </button>
    {analysis.isPending && <p role="status" className="mt-4 text-sm">Gathering evidence and validating the result...</p>}
    {analysis.isError && <div className="mt-4"><ErrorNotice message={analysis.error.message} onRetry={() => void submit()} /></div>}
    {!view && !analysis.isPending && !analysis.isError && <p className="mt-8 text-sm text-slate-400">Ask a question to get started.</p>}
    {view && <div className="mt-8 border-t border-slate-800 pt-6">
      <ResultContent view={view} />
      {canSave && <div className="mt-6 border-t border-slate-800 pt-4">
        <button type="button" className="button-primary" disabled={save.isPending || save.isSuccess || evidenceIds.length === 0} onClick={() => void saveFinding()}>
          {save.isSuccess ? "Finding saved" : save.isPending ? "Saving..." : "Save Finding"}
        </button>
        {evidenceIds.length === 0 && <p className="mt-2 text-xs text-slate-400">Saving requires current code evidence.</p>}
        {save.isError && <div className="mt-3"><ErrorNotice message={save.error.message} /></div>}
      </div>}
    </div>}
  </section>;
}
