import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, CircleDashed, ListTree } from "lucide-react";

import { useAgentTrace } from "../../api/hooks";
import { ErrorNotice } from "../common/Shell";
import { EmptyState } from "../common/EmptyState";

const labels: Record<string, string> = {
  retrieve_memory: "Retrieved repository memory", search_codebase: "Searched repository",
  find_symbol: "Located symbols", find_references: "Found references",
  read_file: "Read file", read_file_range: "Read file range",
  get_related_files: "Expanded related symbols", inspect_repository: "Inspected repository",
  search_web: "Searched external documentation", save_memory: "Saved memory",
};

function StepStatusIcon({ ok }: { ok: boolean }) {
  return ok
    ? <CheckCircle2 size={14} strokeWidth={1.75} className="shrink-0 text-success" />
    : <AlertCircle size={14} strokeWidth={1.75} className="shrink-0 text-danger" />;
}

export function AgentTrace({ runId }: { runId: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const trace = useAgentTrace(runId);

  return (
    <section aria-label="Agent trace" className="panel">
      <div className="panel-header">
        <h2 className="flex items-center gap-2 text-sm font-medium text-ink-primary">
          <ListTree size={15} strokeWidth={1.75} className="text-ink-muted" /> Agent Trace
        </h2>
        {runId && (
          <button type="button" className="button-ghost" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Hide details" : "Show details"}
            {expanded ? <ChevronUp size={14} strokeWidth={1.75} /> : <ChevronDown size={14} strokeWidth={1.75} />}
          </button>
        )}
      </div>

      <div className="panel-body">
        {!runId && <EmptyState icon={<CircleDashed size={18} strokeWidth={1.75} />} title="Run an analysis to see its tool and model steps." />}
        {runId && trace.isPending && <p role="status" className="text-sm text-ink-secondary">Loading trace...</p>}
        {runId && trace.isError && <ErrorNotice message={trace.error.message} onRetry={() => void trace.refetch()} />}

        {trace.data && <>
          {trace.data.tool_calls.length === 0 && trace.data.model_executions.length === 0 && (
            <p className="text-sm text-ink-secondary">No steps were recorded.</p>
          )}
          <ol className="grid gap-2 md:grid-cols-2">
            {trace.data.tool_calls.map((call) => (
              <li key={call.id} className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-1 px-3 py-2 text-sm text-ink-secondary">
                <StepStatusIcon ok={call.status === "OK"} />
                <span className={call.status === "OK" ? "text-success" : "text-danger"}>{call.status === "OK" ? "Done:" : "Error:"}</span>
                {labels[call.tool_name] ?? call.tool_name}
              </li>
            ))}
            {trace.data.model_executions.map((execution) => (
              <li key={execution.id} className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-1 px-3 py-2 text-sm text-ink-secondary">
                <StepStatusIcon ok={!execution.error} />
                {execution.error ? "Error:" : "Done:"} Generated response with Model {execution.slot}
              </li>
            ))}
          </ol>

          {expanded && (
            <div className="mt-5 space-y-3 border-t border-border-subtle pt-4 text-sm">
              <p className="text-ink-secondary">
                Run status: {trace.data.run.status} · Started: {trace.data.run.started_at} · Completed: {trace.data.run.completed_at ?? "In progress"}
              </p>
              {trace.data.tool_calls.map((call) => (
                <div key={call.id} className="rounded-md border border-border-subtle bg-surface-1 p-3 font-mono text-xs">
                  <p className="font-sans text-sm text-ink-primary">#{call.sequence} {call.tool_name} · {call.status ?? "Pending"} · {call.duration_ms ?? "?"} ms</p>
                  <p className="mt-1 text-ink-muted">{call.started_at} to {call.completed_at ?? "pending"}</p>
                  <p className="mt-1 text-ink-secondary">{call.result_summary ?? "No result summary"}</p>
                  {call.error && <p className="mt-1 text-danger">{call.error}</p>}
                </div>
              ))}
              {trace.data.model_executions.map((execution) => (
                <div key={execution.id} className="rounded-md border border-border-subtle bg-surface-1 p-3 font-mono text-xs">
                  <p className="font-sans text-sm text-ink-primary">Model {execution.slot}: {execution.model_name} · {execution.latency_ms} ms · {execution.validation_status}</p>
                  <p className="mt-1 text-ink-muted">Tokens: {execution.input_tokens ?? "?"} input / {execution.output_tokens ?? "?"} output</p>
                  {execution.schema_validation_status && <p className="mt-1 text-ink-secondary">Schema: {execution.schema_validation_status} · Grounding: {execution.validation_status}</p>}
                  {execution.citation_total != null && <p className="mt-1 text-ink-secondary">Citations: {execution.citation_accepted} accepted, {execution.citation_rejected} rejected of {execution.citation_total}</p>}
                  {Object.entries(execution.citation_rejection_reasons ?? {}).map(([reason, count]) => (
                    <p key={reason} className="mt-1 text-warning">{reason}: {count}</p>
                  ))}
                  {execution.error && <p className="mt-1 text-danger">{execution.error}</p>}
                </div>
              ))}
            </div>
          )}
        </>}
      </div>
    </section>
  );
}
