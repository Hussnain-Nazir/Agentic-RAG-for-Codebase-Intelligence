import { Link, useParams } from "react-router-dom";

import { useIndexStatus, useRepository } from "../../api/hooks";
import { ErrorNotice, Shell } from "../../components/common/Shell";

export function IndexingStatusPage() {
  const { id = "" } = useParams();
  const repository = useRepository(id);
  const status = useIndexStatus(id);
  const index = status.data;
  const percent = index && index.files_discovered > 0
    ? Math.min(100, Math.round(index.files_processed / index.files_discovered * 100))
    : 0;

  return <Shell title="Repository indexing">
    {repository.isPending && <p role="status">Loading repository...</p>}
    {repository.isError && <ErrorNotice message={repository.error.message} onRetry={() => void repository.refetch()} />}
    {repository.data && <p className="mb-6 text-slate-400">{repository.data.name} / {repository.data.selected_branch}</p>}
    {status.isPending && <p role="status">Loading index status...</p>}
    {status.isError && <ErrorNotice message={status.error.message} onRetry={() => void status.refetch()} />}
    {index && <section className="max-w-2xl rounded-xl border border-slate-800 bg-slate-900 p-7">
      <div className="flex items-center justify-between"><h2 className="text-xl font-semibold">{index.state}</h2><span>{percent}%</span></div>
      <progress aria-label="Indexing progress" value={percent} max={100} className="mt-5 w-full" />
      <p className="mt-3 text-sm text-slate-400">{index.files_processed} of {index.files_discovered} files processed</p>
      {index.files_failed > 0 && <p className="mt-4 text-amber-300">{index.files_failed} files could not be indexed.</p>}
      {index.size_warning && <p className="mt-4 text-amber-300">This repository exceeds the tested 2,000-file scale. Retrieval quality and latency are untested at this size.</p>}
      {index.failure_reason && <div className="mt-4"><ErrorNotice message={index.failure_reason} /></div>}
      {index.state === "FAILED" && <p className="mt-5 text-sm text-slate-400">Retry is not available for this import yet.</p>}
      <Link to="/dashboard" className="mt-6 inline-block text-cyan-300 underline">Back to repositories</Link>
    </section>}
  </Shell>;
}
