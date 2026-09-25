import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useModelsConfig, useRepository } from "../../api/hooks";
import type { ModelSlot } from "../../api/types";
import { AgentTrace } from "../../components/workspace/AgentTrace";
import { AnalysisWorkspace, evidenceForView } from "../../components/workspace/AnalysisWorkspace";
import type { AnalysisMode, AnalysisView } from "../../components/workspace/AnalysisWorkspace";
import { EvidencePanel } from "../../components/workspace/EvidencePanel";
import { RepositoryTree } from "../../components/workspace/RepositoryTree";
import type { FileSelection } from "../../components/workspace/RepositoryTree";
import { ErrorNotice, Shell } from "../../components/common/Shell";

export function WorkspacePage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const repository = useRepository(id);
  const models = useModelsConfig();
  const [slot, setSlot] = useState<ModelSlot>("A");
  const [mode, setMode] = useState<AnalysisMode>("ask");
  const [view, setView] = useState<AnalysisView | null>(null);
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
  return <Shell title="Repository Workspace" wide>
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div>
        {repository.isPending && <p role="status">Loading repository...</p>}
        {repository.isError && <ErrorNotice message={repository.error.message} onRetry={() => void repository.refetch()} />}
        {repository.data && <><h2 className="text-xl font-semibold">{repository.data.name}</h2><p className="text-sm text-slate-400">Branch: {repository.data.selected_branch}</p></>}
        {repository.data?.index && !["READY", "PARTIAL"].includes(repository.data.index.state) && <Link className="mt-2 inline-block text-sm text-amber-300 underline" to={`/repositories/${id}/indexing`}>Index state: {repository.data.index.state}</Link>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {models.isPending && <span role="status" className="text-sm">Loading models...</span>}
        {models.isError && <ErrorNotice message={models.error.message} onRetry={() => void models.refetch()} />}
        {models.data && !models.data.model_a.name && !models.data.model_b.name && <p className="text-sm text-amber-300">No model slot is configured.</p>}
        {models.data && <><label htmlFor="model-slot" className="text-sm">Model</label><select id="model-slot" className="input w-auto" value={slot} onChange={(event) => setSlot(event.target.value as ModelSlot)}>
          <option value="A" disabled={!models.data.model_a.name}>A: {models.data.model_a.name ?? "Not configured"}</option>
          <option value="B" disabled={!models.data.model_b.name}>B: {models.data.model_b.name ?? "Not configured"}</option>
        </select></>}
        <button type="button" className="button-primary" onClick={() => { setMode("compare"); setView(null); }}>Compare Models</button>
      </div>
      <nav className="flex gap-4 text-sm"><Link className="text-cyan-300 underline" to={`/repositories/${id}/memory`}>Memory</Link><Link className="text-cyan-300 underline" to={`/repositories/${id}/findings`}>Findings</Link></nav>
    </div>
    <div className="grid gap-5 lg:grid-cols-[minmax(14rem,1fr)_minmax(24rem,2fr)_minmax(18rem,1.25fr)]">
      <RepositoryTree repositoryId={id} onSelect={setSelected} />
      <AnalysisWorkspace repositoryId={id} modelSlot={slot} mode={mode} onModeChange={setMode} view={view} onResult={setView} />
      <EvidencePanel repositoryId={id} evidence={evidenceForView(view)} selected={selected} onSelect={setSelected} />
    </div>
    <AgentTrace runId={view?.runId ?? null} />
  </Shell>;
}
