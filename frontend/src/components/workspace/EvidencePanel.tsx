import { useFileContent } from "../../api/hooks";
import type { Evidence } from "../../api/types";
import { ErrorNotice } from "../common/Shell";
import type { FileSelection } from "./RepositoryTree";

export function EvidencePanel({ repositoryId, evidence, selected, onSelect }: {
  repositoryId: string; evidence: Evidence[]; selected: FileSelection | null;
  onSelect: (selection: FileSelection) => void;
}) {
  const content = useFileContent(repositoryId, selected?.path ?? null, selected?.startLine, selected?.endLine);
  return <section aria-label="Evidence panel" className="panel min-w-0">
    <h2 className="text-lg font-semibold">Evidence</h2>
    {evidence.length === 0 && <p className="mt-4 text-sm text-slate-400">Citations will appear after an analysis.</p>}
    <ul className="mt-4 max-h-72 space-y-2 overflow-y-auto">{evidence.map((item) => <li key={item.evidence_id}>
      {item.file_path ? <button type="button" className="w-full rounded-lg border border-slate-700 p-3 text-left hover:border-cyan-400" onClick={() => onSelect({ path: item.file_path!, startLine: item.start_line ?? undefined, endLine: item.end_line ?? undefined })}>
        <span className="block break-all text-sm font-medium">{item.file_path}:{item.start_line ?? "?"}-{item.end_line ?? "?"}</span>
        <span className="mt-1 block text-xs text-slate-400">{item.symbol || item.source_type}</span>
        <span className="mt-2 block max-h-20 overflow-hidden whitespace-pre-wrap text-xs text-slate-300">{item.content_excerpt}</span>
      </button> : <div className="rounded-lg border border-slate-700 p-3 text-xs text-slate-300">{item.source_type} evidence: {item.content_excerpt}</div>}
    </li>)}</ul>
    <div className="mt-5 border-t border-slate-800 pt-4">
      <h3 className="text-sm font-semibold">File viewer</h3>
      {!selected && <p className="mt-2 text-sm text-slate-400">Select evidence or a file to inspect it.</p>}
      {selected && content.isPending && <p role="status" className="mt-2 text-sm">Loading file content...</p>}
      {selected && content.isError && <div className="mt-2"><ErrorNotice message={content.error.message} onRetry={() => void content.refetch()} /></div>}
      {content.data && <div className="mt-3">
        <p className="break-all text-xs text-cyan-300">{content.data.path}:{content.data.start_line}-{content.data.end_line}</p>
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-xs">{content.data.content}</pre>
      </div>}
    </div>
  </section>;
}
