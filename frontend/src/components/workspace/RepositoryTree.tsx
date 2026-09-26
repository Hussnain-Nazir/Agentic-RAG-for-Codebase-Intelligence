import { useState } from "react";
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, Search as SearchIcon } from "lucide-react";

import { useFiles, useSymbols } from "../../api/hooks";
import type { FileTreeEntry } from "../../api/types";
import { ErrorNotice } from "../common/Shell";

export interface FileSelection { path: string; startLine?: number; endLine?: number }

interface TreeContext {
  repositoryId: string;
  search: string;
  selectedPath: string | null;
  onSelect: (selection: FileSelection) => void;
}

function TreeChildren({ path, depth, ctx }: { path: string; depth: number; ctx: TreeContext }) {
  const files = useFiles(ctx.repositoryId, path);
  const filtered = (files.data ?? []).filter((item) => item.name.toLowerCase().includes(ctx.search.toLowerCase()));

  if (files.isPending) {
    return <li style={{ paddingLeft: 10 + depth * 14 }} className="py-1 text-xs text-ink-muted">Loading...</li>;
  }
  if (files.isError) {
    return <li className="py-1"><ErrorNotice message={files.error.message} onRetry={() => void files.refetch()} /></li>;
  }
  if (filtered.length === 0) {
    return (
      <li style={{ paddingLeft: 10 + depth * 14 }} className="py-1.5 text-xs text-ink-muted">
        {path ? "Empty directory." : "No files in this view."}
      </li>
    );
  }
  const sorted = [...filtered].sort((a, b) => (a.is_directory === b.is_directory ? a.name.localeCompare(b.name) : a.is_directory ? -1 : 1));
  return <>{sorted.map((entry) => <TreeNode key={entry.path} entry={entry} depth={depth} ctx={ctx} />)}</>;
}

function TreeNode({ entry, depth, ctx }: { entry: FileTreeEntry; depth: number; ctx: TreeContext }) {
  const [expanded, setExpanded] = useState(false);
  const active = ctx.selectedPath === entry.path;

  if (!entry.is_directory) {
    return (
      <li>
        <button
          type="button"
          className="tree-row"
          data-active={active}
          style={{ paddingLeft: 10 + depth * 14 }}
          onClick={() => ctx.onSelect({ path: entry.path })}
          title={entry.path}
        >
          <File size={14} strokeWidth={1.6} className="shrink-0 text-ink-muted" />
          <span className="truncate">{entry.name}</span>
        </button>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        className="tree-row"
        style={{ paddingLeft: 10 + depth * 14 }}
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        title={entry.path}
      >
        {expanded ? <ChevronDown size={14} strokeWidth={1.75} className="shrink-0 text-ink-muted" /> : <ChevronRight size={14} strokeWidth={1.75} className="shrink-0 text-ink-muted" />}
        {expanded ? <FolderOpen size={14} strokeWidth={1.6} className="shrink-0 text-accent-hover" /> : <Folder size={14} strokeWidth={1.6} className="shrink-0 text-ink-muted" />}
        <span className="truncate font-medium">{entry.name}</span>
      </button>
      {expanded && (
        <ul className="animate-fade-in">
          <TreeChildren path={entry.path} depth={depth + 1} ctx={ctx} />
        </ul>
      )}
    </li>
  );
}

export function RepositoryTree({ repositoryId, onSelect }: { repositoryId: string; onSelect: (selection: FileSelection) => void }) {
  const [search, setSearch] = useState("");
  const symbols = useSymbols(repositoryId, search);
  const ctx: TreeContext = { repositoryId, search, selectedPath: null, onSelect };

  return (
    <section aria-label="Repository tree" className="panel flex min-w-0 flex-col">
      <div className="panel-header">
        <h2 className="text-sm font-medium text-ink-primary">Repository tree</h2>
      </div>
      <div className="panel-body pb-2">
        <label className="sr-only" htmlFor="tree-search">Search files and symbols</label>
        <div className="relative">
          <SearchIcon size={14} strokeWidth={1.75} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input id="tree-search" className="input pl-8 text-sm" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="File or symbol" />
        </div>
      </div>
      <ul className="max-h-[26rem] overflow-y-auto px-1 pb-2">
        <TreeChildren path="" depth={0} ctx={ctx} />
      </ul>
      {search.trim() && (
        <div className="border-t border-border-subtle px-3 py-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-ink-muted">Symbols</h3>
          {symbols.isPending && <p role="status" className="mt-2 text-sm text-ink-secondary">Searching symbols...</p>}
          {symbols.isError && <div className="mt-2"><ErrorNotice message={symbols.error.message} onRetry={() => void symbols.refetch()} /></div>}
          {symbols.data?.length === 0 && <p className="mt-2 text-sm text-ink-muted">No matching symbols.</p>}
          <ul className="mt-1 space-y-0.5">{symbols.data?.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="tree-row flex-col !items-start"
                onClick={() => onSelect({ path: item.file_path, startLine: item.start_line, endLine: item.end_line })}
              >
                <span className="font-medium text-ink-primary">{item.name}</span>
                <span className="truncate text-xs text-ink-muted">{item.file_path}:{item.start_line}</span>
              </button>
            </li>
          ))}</ul>
        </div>
      )}
    </section>
  );
}
