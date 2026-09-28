import { Link } from "react-router-dom";
import { GitBranch } from "lucide-react";

import { useRepository } from "../../api/hooks";
import { ErrorNotice } from "../common/Shell";
import { IndexStateBadge } from "../common/StatusBadge";

export function RepositoryHeader({ repositoryId }: { repositoryId: string }) {
  const repository = useRepository(repositoryId);

  if (repository.isPending) return <p role="status" className="py-2 text-sm text-ink-secondary">Loading repository...</p>;
  if (repository.isError) return <div className="py-2"><ErrorNotice message={repository.error.message} onRetry={() => void repository.refetch()} /></div>;
  if (!repository.data) return null;

  const notReady = repository.data.index && !["READY", "PARTIAL"].includes(repository.data.index.state);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <h1 className="truncate text-[17px] font-semibold tracking-tight text-ink-primary">{repository.data.name}</h1>
        <span className="badge">{repository.data.source_type === "github" ? "GitHub" : "ZIP upload"}</span>
        <span className="inline-flex items-center gap-1 text-sm text-ink-secondary"><GitBranch size={13} strokeWidth={1.75} />{repository.data.selected_branch}</span>
        {repository.data.index && <IndexStateBadge state={repository.data.index.state} />}
      </div>
      {notReady && (
        <Link className="text-sm font-medium text-warning underline underline-offset-2" to={`/repositories/${repositoryId}/indexing`}>
          View indexing status
        </Link>
      )}
    </div>
  );
}
