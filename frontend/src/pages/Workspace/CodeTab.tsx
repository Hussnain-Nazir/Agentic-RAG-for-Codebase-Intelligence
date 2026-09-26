import { useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { useFileContent } from "../../api/hooks";
import { RepositoryTree } from "../../components/workspace/RepositoryTree";
import type { FileSelection } from "../../components/workspace/RepositoryTree";
import { CodeViewer } from "../../components/workspace/CodeViewer";
import { ErrorNotice } from "../../components/common/Shell";
import { EmptyState } from "../../components/common/EmptyState";
import type { WorkspaceContext } from "./WorkspacePage";

export function CodeTab() {
  const { repositoryId } = useOutletContext<WorkspaceContext>();
  const [params] = useSearchParams();
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [selected, setSelected] = useState<FileSelection | null>(() => {
    const path = params.get("path");
    if (!path) return null;
    const startLine = Number(params.get("start_line"));
    const endLine = Number(params.get("end_line"));
    return { path, startLine: startLine > 0 ? startLine : undefined, endLine: endLine > 0 ? endLine : undefined };
  });
  const content = useFileContent(repositoryId, selected?.path ?? null, selected?.startLine, selected?.endLine);

  return (
    <div className="flex h-full min-h-0 gap-3">
      {explorerOpen ? (
        <div className="w-72 shrink-0">
          <div className="flex items-center justify-between px-1 pb-2">
            <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Explorer</span>
            <button type="button" className="icon-button" aria-label="Collapse explorer" onClick={() => setExplorerOpen(false)}>
              <PanelLeftClose size={15} strokeWidth={1.75} />
            </button>
          </div>
          <RepositoryTree repositoryId={repositoryId} onSelect={setSelected} />
        </div>
      ) : (
        <button type="button" className="icon-button h-fit" aria-label="Expand explorer" onClick={() => setExplorerOpen(true)}>
          <PanelLeftOpen size={16} strokeWidth={1.75} />
        </button>
      )}

      <div className="min-h-0 min-w-0 flex-1">
        {!selected && <EmptyState title="Select a file to inspect it." description="Browse the repository explorer or open a citation from Analyze." />}
        {selected && content.isPending && <p role="status" className="text-sm text-ink-secondary">Loading file content...</p>}
        {selected && content.isError && <ErrorNotice message={content.error.message} onRetry={() => void content.refetch()} />}
        {content.data && (
          <div className="h-full">
            <CodeViewer
              path={content.data.path}
              content={content.data.content}
              startLine={content.data.start_line}
              highlightStart={selected?.startLine ?? null}
              highlightEnd={selected?.endLine ?? null}
              fill
            />
          </div>
        )}
      </div>
    </div>
  );
}
