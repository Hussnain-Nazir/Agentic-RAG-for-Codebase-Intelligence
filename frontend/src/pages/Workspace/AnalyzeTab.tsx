import { useEffect, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { ArrowUpRight, X } from "lucide-react";

import { useModelsConfig } from "../../api/hooks";
import type { Evidence, ModelSlot } from "../../api/types";
import { AnalysisWorkspace, evidenceForView } from "../../components/workspace/AnalysisWorkspace";
import type { AnalysisMode, AnalysisView } from "../../components/workspace/AnalysisWorkspace";
import { EvidencePanel } from "../../components/workspace/EvidencePanel";
import type { FileSelection } from "../../components/workspace/RepositoryTree";
import { ErrorNotice } from "../../components/common/Shell";
import type { WorkspaceContext } from "./WorkspacePage";

export function AnalyzeTab() {
  const { repositoryId, setLastRunId } = useOutletContext<WorkspaceContext>();
  const navigate = useNavigate();
  const models = useModelsConfig();
  const [slot, setSlot] = useState<ModelSlot>("A");
  const [mode, setMode] = useState<AnalysisMode>("ask");
  const [view, setView] = useState<AnalysisView | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<FileSelection | null>(null);

  useEffect(() => {
    if (models.data && !models.data.model_a.name && models.data.model_b.name) setSlot("B");
  }, [models.data]);

  function handleResult(next: AnalysisView | null) {
    setView(next);
    if (next) setLastRunId(next.runId);
  }

  function openEvidence(evidence: Evidence) {
    setSelectedFile(evidence.file_path ? { path: evidence.file_path, startLine: evidence.start_line ?? undefined, endLine: evidence.end_line ?? undefined } : null);
    setDrawerOpen(true);
  }

  function openInCode() {
    if (!selectedFile) return;
    const params = new URLSearchParams({ path: selectedFile.path });
    if (selectedFile.startLine) params.set("start_line", String(selectedFile.startLine));
    if (selectedFile.endLine) params.set("end_line", String(selectedFile.endLine));
    navigate(`/repositories/${repositoryId}/code?${params}`);
  }

  const evidence = evidenceForView(view);

  const modelDropdown = models.data ? (
    <div className="flex items-center gap-2">
      <label htmlFor="model-slot" className="text-sm text-ink-secondary">Model</label>
      <select id="model-slot" className="input w-auto py-1.5 text-sm" value={slot} onChange={(event) => setSlot(event.target.value as ModelSlot)}>
        <option value="A" disabled={!models.data.model_a.name}>A: {models.data.model_a.name ?? "Not configured"}</option>
        <option value="B" disabled={!models.data.model_b.name}>B: {models.data.model_b.name ?? "Not configured"}</option>
      </select>
    </div>
  ) : models.isError ? (
    <ErrorNotice message={models.error.message} onRetry={() => void models.refetch()} />
  ) : (
    <span role="status" className="text-sm text-ink-secondary">Loading models...</span>
  );

  return (
    <div className="relative flex h-full min-h-0">
      <div className="min-w-0 flex-1">
        <AnalysisWorkspace
          repositoryId={repositoryId}
          modelSlot={slot}
          mode={mode}
          onModeChange={setMode}
          view={view}
          onResult={handleResult}
          onOpenEvidence={openEvidence}
          composerLeft={modelDropdown}
          onClear={() => { setLastRunId(null); setSelectedFile(null); setDrawerOpen(false); }}
        />
      </div>

      {drawerOpen && (
        <div className="absolute inset-y-0 right-0 z-10 flex w-full max-w-md animate-slide-up flex-col border-l border-border bg-surface-2 shadow-overlay">
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
            <h2 className="text-sm font-medium text-ink-primary">Evidence ({evidence.length})</h2>
            <div className="flex items-center gap-1">
              {selectedFile && (
                <button type="button" className="button-ghost" onClick={openInCode}>
                  Open in Code <ArrowUpRight size={13} strokeWidth={2} />
                </button>
              )}
              <button type="button" className="icon-button" aria-label="Close evidence panel" onClick={() => setDrawerOpen(false)}>
                <X size={16} strokeWidth={1.75} />
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <EvidencePanel repositoryId={repositoryId} evidence={evidence} selected={selectedFile} onSelect={setSelectedFile} bare />
          </div>
        </div>
      )}

      {!drawerOpen && evidence.length > 0 && (
        <button
          type="button"
          className="button-secondary absolute right-3 top-3 z-10"
          onClick={() => setDrawerOpen(true)}
        >
          View evidence ({evidence.length})
        </button>
      )}
    </div>
  );
}
