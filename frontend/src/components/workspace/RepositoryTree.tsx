import { useState } from "react";

import { useFiles, useSymbols } from "../../api/hooks";
import { ErrorNotice } from "../common/Shell";

export interface FileSelection { path: string; startLine?: number; endLine?: number }

export function RepositoryTree({ repositoryId, onSelect }: { repositoryId: string; onSelect: (selection: FileSelection) => void }) {
  const [path, setPath] = useState("");
  const [search, setSearch] = useState("");
  const files = useFiles(repositoryId, path);
  const symbols = useSymbols(repositoryId, search);
  const filtered = files.data?.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())) ?? [];
  return <section aria-label="Repository tree" className="panel min-w-0">
    <h2 className="text-lg font-semibold">Repository tree</h2>
    <label className="label mt-4" htmlFor="tree-search">Search files and symbols</label>
    <input id="tree-search" className="input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="File or symbol" />
    {path && <button type="button" className="mt-3 text-sm text-cyan-300 underline" onClick={() => setPath(path.split("/").slice(0, -1).join("/"))}>Back to parent</button>}
    <p className="mt-4 text-xs text-slate-400">{path || "Repository root"}</p>
    {files.isPending && <p role="status" className="mt-3">Loading files...</p>}
    {files.isError && <div className="mt-3"><ErrorNotice message={files.error.message} onRetry={() => void files.refetch()} /></div>}
    {files.data && filtered.length === 0 && <p className="mt-3 text-sm text-slate-400">No files in this view.</p>}
    <ul className="mt-3 space-y-1">{filtered.map((item) => <li key={item.path}>
      <button type="button" className="w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-slate-800" onClick={() => item.is_directory ? setPath(item.path) : onSelect({ path: item.path })}>
        <span className="mr-2 text-slate-400">{item.is_directory ? "Folder" : "File"}</span>{item.name}
      </button>
    </li>)}</ul>
    {search.trim() && <div className="mt-5 border-t border-slate-800 pt-4">
      <h3 className="text-sm font-semibold">Symbols</h3>
      {symbols.isPending && <p role="status" className="mt-2 text-sm">Searching symbols...</p>}
      {symbols.isError && <div className="mt-2"><ErrorNotice message={symbols.error.message} onRetry={() => void symbols.refetch()} /></div>}
      {symbols.data?.length === 0 && <p className="mt-2 text-sm text-slate-400">No matching symbols.</p>}
      <ul className="mt-2 space-y-1">{symbols.data?.map((item) => <li key={item.id}>
        <button type="button" className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-slate-800" onClick={() => onSelect({ path: item.file_path, startLine: item.start_line, endLine: item.end_line })}>
          <span className="block font-medium">{item.name}</span><span className="block truncate text-xs text-slate-400">{item.file_path}:{item.start_line}</span>
        </button>
      </li>)}</ul>
    </div>}
  </section>;
}
