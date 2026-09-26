import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { BrainCircuit, ClipboardList, GitBranch, GitCompare, ListTree } from "lucide-react";

import { useModelsConfig, useRepository } from "../../api/hooks";
import type { ModelSlot } from "../../api/types";
import { AgentTrace } from "../../components/workspace/AgentTrace";
import { AnalysisWorkspace, evidenceForView } from "../../components/workspace/AnalysisWorkspace";
import type { AnalysisMode, AnalysisView } from "../../components/workspace/AnalysisWorkspace";
import { EvidencePanel } from "../../components/workspace/EvidencePanel";
import { RepositoryTree } from "../../components/workspace/RepositoryTree";
import type { FileSelection } from "../../components/workspace/RepositoryTree";
import { ErrorNotice, Shell } from "../../components/common/Shell";
import { IndexStateBadge } from "../../components/common/StatusBadge";

type WorkspaceTab = "investigate" | "trace";

export function WorkspacePage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const repository = useRepository(id);
  const models = useModelsConfig();
  const [slot, setSlot] = useState<ModelSlot>("A");
  const [mode, setMode] = useState<AnalysisMode>("ask");
  const [view, setView] = useState<AnalysisView | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("investigate");

  useEffect(() => {
    if (models.data && !models.data.model_a.name && models.data.model_b.name) setSlot("B");
  }, [models.data]);

  const [selected, setSelected] = useState<FileSelection | null>(() => {
    const path = params.get("path");
    if (!path) return null;
    const startLine = Number(params.get("start_line"));
    const endLine = Number(params.get("end_line"));
    return { path, startLine: startLine > 0 ? startLine : undefined, endLine: endLine > 0 ? endLine : undefined };
  });

  return (
    <Shell title="Repository Workspace" wide>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-surface-2 p-4">
        <div className="min-w-0">
          {repository.isPending && <p role="status" className="text-sm text-ink-secondary">Loading repository...</p>}
          {repository.isError && <ErrorNotice message={repository.error.message} onRetry={() => void repository.refetch()} />}
          {repository.data && (
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="truncate text-lg font-semibold text-ink-primary">{repository.data.name}</h2>
              {repository.data.index && <IndexStateBadge state={repository.data.index.state} />}
              <span className="inline-flex items-center gap-1 text-sm text-ink-secondary"><GitBranch size={13} strokeWidth={1.75} />{repository.data.selected_branch}</span>
            </div>
          )}
          {repository.data?.index && !["READY", "PARTIAL"].includes(repository.data.index.state) && (
            <Link className="mt-1.5 inline-block text-sm font-medium text-warning underline underline-offset-2" to={`/repositories/${id}/indexing`}>
              Index state: {repository.data.index.state}
            </Link>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {models.isPending && <span role="status" className="text-sm text-ink-secondary">Loading models...</span>}
          {models.isError && <ErrorNotice message={models.error.message} onRetry={() => void models.refetch()} />}
          {models.data && !models.data.model_a.name && !models.data.model_b.name && <p className="text-sm text-warning">No model slot is configured.</p>}
          {models.data && (
            <div className="flex items-center gap-2">
              <label htmlFor="model-slot" className="text-sm text-ink-secondary">Model</label>
              <select id="model-slot" className="input w-auto" value={slot} onChange={(event) => setSlot(event.target.value as ModelSlot)}>
                <option value="A" disabled={!models.data.model_a.name}>A: {models.data.model_a.name ?? "Not configured"}</option>
                <option value="B" disabled={!models.data.model_b.name}>B: {models.data.model_b.name ?? "Not configured"}</option>
              </select>
            </div>
          )}
          <button type="button" className="button-secondary" onClick={() => { setMode("compare"); setView(null); setTab("investigate"); }}>
            <GitCompare size={15} strokeWidth={1.75} /> Compare Models
          </button>
        </div>

        <nav className="flex gap-4 text-sm">
          <Link className="inline-flex items-center gap-1.5 font-medium text-accent-hover" to={`/repositories/${id}/memory`}>
            <BrainCircuit size={14} strokeWidth={1.75} /> Memory
          </Link>
          <Link className="inline-flex items-center gap-1.5 font-medium text-accent-hover" to={`/repositories/${id}/findings`}>
            <ClipboardList size={14} strokeWidth={1.75} /> Findings
          </Link>
        </nav>
      </div>

      <div role="tablist" aria-label="Workspace section" className="mb-4 flex w-fit gap-1 rounded-md border border-border bg-surface-1 p-1">
        <button type="button" role="tab" aria-selected={tab === "investigate"} className="tab-trigger" onClick={() => setTab("investigate")}>
          <ListTree size={14} strokeWidth={1.75} /> Explore &amp; Analyze
        </button>
        <button type="button" role="tab" aria-selected={tab === "trace"} className="tab-trigger" onClick={() => setTab("trace")}>
          <GitCompare size={14} strokeWidth={1.75} /> Agent Trace
        </button>
      </div>

      {tab === "investigate" ? (
        <div className="grid gap-5 lg:grid-cols-[minmax(13rem,0.9fr)_minmax(22rem,1.4fr)_minmax(20rem,1.1fr)]">
          <RepositoryTree repositoryId={id} onSelect={setSelected} />
          <AnalysisWorkspace repositoryId={id} modelSlot={slot} mode={mode} onModeChange={setMode} view={view} onResult={setView} />
          <EvidencePanel repositoryId={id} evidence={evidenceForView(view)} selected={selected} onSelect={setSelected} />
        </div>
      ) : (
        <AgentTrace runId={view?.runId ?? null} />
      )}
    </Shell>
  );
}
