import { Link } from "react-router-dom";
import { ArrowRight, FolderGit2, GitBranch, Plus, Upload } from "lucide-react";

import { useRepositories } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";
import { EmptyState } from "../../components/common/EmptyState";
import { IndexStateBadge } from "../../components/common/StatusBadge";

export function DashboardPage() {
  const repositories = useRepositories();
  return (
    <Shell title="Repositories">
      <div className="mb-6 flex items-center justify-between gap-4">
        <p className="text-sm text-ink-secondary">Connected repositories available for investigation.</p>
        <Link className="button-primary" to="/repositories/new">
          <Plus size={16} strokeWidth={2} /> Add repository
        </Link>
      </div>

      {repositories.isPending && <SkeletonList />}
      {repositories.isError && <ErrorNotice message={repositories.error.message} onRetry={() => void repositories.refetch()} />}

      {repositories.data?.length === 0 && (
        <EmptyState
          icon={<Upload size={20} strokeWidth={1.75} />}
          title="Add your first repository."
          description="Connect a GitHub repository or upload a ZIP archive to begin indexing."
          action={<Link to="/repositories/new" className="button-primary"><Plus size={16} strokeWidth={2} /> Add repository</Link>}
        />
      )}

      {repositories.data && repositories.data.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {repositories.data.map((repository) => (
            <article key={repository.id} className="panel flex flex-col p-5 transition-colors duration-150 hover:border-border-strong">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2.5">
                  <FolderGit2 size={17} strokeWidth={1.75} className="shrink-0 text-ink-muted" />
                  <h2 className="truncate text-[15px] font-medium text-ink-primary">{repository.name}</h2>
                </div>
                <IndexStateBadge state={repository.index?.state ?? "PENDING"} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
                <span className="badge">{repository.source_type === "github" ? "GitHub" : "ZIP upload"}</span>
                <span className="inline-flex items-center gap-1"><GitBranch size={12} strokeWidth={1.75} />{repository.selected_branch}</span>
              </div>
              <div className="mt-5 flex items-center gap-4 border-t border-border-subtle pt-4 text-sm">
                <Link className="inline-flex items-center gap-1 font-medium text-accent-hover" to={`/repositories/${repository.id}`}>
                  Open workspace <ArrowRight size={14} strokeWidth={2} />
                </Link>
                <Link className="text-ink-secondary hover:text-ink-primary" to={`/repositories/${repository.id}`}>Ask</Link>
                <Link className="text-ink-secondary hover:text-ink-primary" to={`/repositories/${repository.id}/indexing`}>Index status</Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </Shell>
  );
}
