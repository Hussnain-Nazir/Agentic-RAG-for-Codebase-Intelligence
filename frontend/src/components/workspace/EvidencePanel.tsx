import { FileCode2, MapPin } from "lucide-react";

import { useFileContent } from "../../api/hooks";
import type { Evidence } from "../../api/types";
import { ErrorNotice } from "../common/Shell";
import { EmptyState } from "../common/EmptyState";
import { CodeViewer } from "./CodeViewer";
import type { FileSelection } from "./RepositoryTree";

export function EvidencePanel({ repositoryId, evidence, selected, onSelect }: {
  repositoryId: string; evidence: Evidence[]; selected: FileSelection | null;
  onSelect: (selection: FileSelection) => void;
}) {
  const content = useFileContent(repositoryId, selected?.path ?? null, selected?.startLine, selected?.endLine);
  return (
    <section aria-label="Evidence panel" className="panel flex min-w-0 flex-col">
      <div className="panel-header">
        <h2 className="text-sm font-medium text-ink-primary">Evidence</h2>
        {evidence.length > 0 && <span className="badge">{evidence.length}</span>}
      </div>

      <div className="panel-body pb-3">
        {evidence.length === 0 && <p className="text-sm text-ink-muted">Citations will appear after an analysis.</p>}
        <ul className="max-h-56 space-y-2 overflow-y-auto">
          {evidence.map((item) => (
            <li key={item.evidence_id}>
              {item.file_path ? (
                <button
                  type="button"
                  className="w-full rounded-md border border-border bg-surface-1 p-3 text-left transition-colors duration-150 hover:border-accent-muted hover:bg-surface-hover"
                  onClick={() => onSelect({ path: item.file_path!, startLine: item.start_line ?? undefined, endLine: item.end_line ?? undefined })}
                >
                  <span className="flex items-center gap-1.5 truncate font-mono text-xs font-medium text-accent-hover">
                    <MapPin size={12} strokeWidth={2} className="shrink-0" />
                    {item.file_path}:{item.start_line ?? "?"}-{item.end_line ?? "?"}
                  </span>
                  <span className="mt-1 block text-xs text-ink-muted">{item.symbol || item.source_type}</span>
                  <span className="mt-2 block max-h-16 overflow-hidden whitespace-pre-wrap break-words font-mono text-xs text-ink-secondary">{item.content_excerpt}</span>
                </button>
              ) : (
                <div className="rounded-md border border-border bg-surface-1 p-3 text-xs text-ink-secondary">
                  <span className="badge mb-1.5">{item.source_type}</span>
                  <p>{item.content_excerpt}</p>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-border-subtle p-4">
        <h3 className="mb-3 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-muted">
          <FileCode2 size={13} strokeWidth={1.75} /> File viewer
        </h3>
        {!selected && <EmptyState title="Select evidence or a file to inspect it." />}
        {selected && content.isPending && <p role="status" className="text-sm text-ink-secondary">Loading file content...</p>}
        {selected && content.isError && <ErrorNotice message={content.error.message} onRetry={() => void content.refetch()} />}
        {content.data && (
          <CodeViewer
            path={content.data.path}
            content={content.data.content}
            startLine={content.data.start_line}
            highlightStart={selected?.startLine ?? null}
            highlightEnd={selected?.endLine ?? null}
          />
        )}
      </div>
    </section>
  );
}
