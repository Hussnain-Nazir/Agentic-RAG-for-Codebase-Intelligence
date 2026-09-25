import { useState } from "react";

import { useAgentTrace } from "../../api/hooks";
import { ErrorNotice } from "../common/Shell";

const labels: Record<string, string> = {
  retrieve_memory: "Retrieved repository memory", search_codebase: "Searched repository",
  find_symbol: "Located symbols", find_references: "Found references",
  read_file: "Read file", read_file_range: "Read file range",
  get_related_files: "Expanded related symbols", inspect_repository: "Inspected repository",
  search_web: "Searched external documentation", save_memory: "Saved memory",
};

export function AgentTrace({ runId }: { runId: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const trace = useAgentTrace(runId);
  return <section aria-label="Agent trace" className="panel mt-6">
    <div className="flex items-center justify-between">
      <h2 className="text-lg font-semibold">Agent Trace</h2>
      {runId && <button type="button" className="text-sm text-cyan-300 underline" onClick={() => setExpanded((value) => !value)}>{expanded ? "Hide details" : "Show details"}</button>}
    </div>
    {!runId && <p className="mt-3 text-sm text-slate-400">Run an analysis to see its tool and model steps.</p>}
    {runId && trace.isPending && <p role="status" className="mt-3 text-sm">Loading trace...</p>}
    {runId && trace.isError && <div className="mt-3"><ErrorNotice message={trace.error.message} onRetry={() => void trace.refetch()} /></div>}
    {trace.data && <>
      {trace.data.tool_calls.length === 0 && trace.data.model_executions.length === 0 && <p className="mt-3 text-sm text-slate-400">No steps were recorded.</p>}
      <ol className="mt-3 grid gap-2 md:grid-cols-2">{trace.data.tool_calls.map((call) => <li key={call.id} className="text-sm">
        <span className={call.status === "OK" ? "text-emerald-300" : "text-rose-300"}>{call.status === "OK" ? "Done:" : "Error:"}</span> {labels[call.tool_name] ?? call.tool_name}
      </li>)}
        {trace.data.model_executions.map((execution) => <li key={execution.id} className="text-sm">{execution.error ? "Error:" : "Done:"} Generated response with Model {execution.slot}</li>)}
      </ol>
      {expanded && <div className="mt-5 space-y-4 border-t border-slate-800 pt-4 text-sm">
        <p>Run status: {trace.data.run.status} · Started: {trace.data.run.started_at} · Completed: {trace.data.run.completed_at ?? "In progress"}</p>
        {trace.data.tool_calls.map((call) => <div key={call.id} className="rounded-lg bg-slate-950 p-3">
          <p>#{call.sequence} {call.tool_name} · {call.status ?? "Pending"} · {call.duration_ms ?? "?"} ms</p>
          <p className="text-xs text-slate-400">{call.started_at} to {call.completed_at ?? "pending"}</p>
          <p>{call.result_summary ?? "No result summary"}</p>
          {call.error && <p className="text-rose-300">{call.error}</p>}
        </div>)}
        {trace.data.model_executions.map((execution) => <div key={execution.id} className="rounded-lg bg-slate-950 p-3">
          <p>Model {execution.slot}: {execution.model_name} · {execution.latency_ms} ms · {execution.validation_status}</p>
          <p className="text-xs text-slate-400">Tokens: {execution.input_tokens ?? "?"} input / {execution.output_tokens ?? "?"} output</p>
          {execution.error && <p className="text-rose-300">{execution.error}</p>}
        </div>)}
      </div>}
    </>}
  </section>;
}
