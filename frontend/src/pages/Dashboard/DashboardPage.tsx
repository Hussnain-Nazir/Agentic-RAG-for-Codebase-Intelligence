import { Link } from "react-router-dom";

import { useRepositories } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";

export function DashboardPage() {
  const repositories = useRepositories();
  return <Shell title="Repositories">
    <div className="mb-6 flex justify-end"><Link className="button-primary" to="/repositories/new">Add repository</Link></div>
    {repositories.isPending && <SkeletonList />}
    {repositories.isError && <ErrorNotice message={repositories.error.message} onRetry={() => void repositories.refetch()} />}
    {repositories.data?.length === 0 && <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900 p-12 text-center">
      <h2 className="text-xl font-medium">Add your first repository.</h2>
      <p className="mt-2 text-slate-400">Connect a GitHub repository or upload a ZIP archive to begin indexing.</p>
      <Link to="/repositories/new" className="button-primary mt-6 inline-block">Add repository</Link>
    </div>}
    {repositories.data && repositories.data.length > 0 && <div className="grid gap-4 md:grid-cols-2">
      {repositories.data.map((repository) => <article key={repository.id} className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold">{repository.name}</h2>
          <span className="badge">{repository.index?.state ?? "PENDING"}</span>
        </div>
        <div className="mt-3 flex gap-2 text-sm text-slate-400">
          <span className="badge">{repository.source_type === "github" ? "GitHub" : "ZIP upload"}</span>
          <span>{repository.selected_branch}</span>
        </div>
        <div className="mt-5 flex items-center gap-4 text-sm">
          <Link className="text-cyan-300 underline" to={`/repositories/${repository.id}`}>Open</Link>
          <Link className="text-cyan-300 underline" to={`/repositories/${repository.id}`}>Ask</Link>
          <Link className="text-slate-300 underline" to={`/repositories/${repository.id}/indexing`}>Index status</Link>
        </div>
      </article>)}
    </div>}
  </Shell>;
}
