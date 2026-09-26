import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { useIndexStatus, useRepository } from "../../api/hooks";
import { ErrorNotice, Shell } from "../../components/common/Shell";
import { IndexStateBadge } from "../../components/common/StatusBadge";

const stageOrder = ["PENDING", "DISCOVERING", "PARSING", "EMBEDDING", "INDEXING", "READY"];

export function IndexingStatusPage() {
  const { id = "" } = useParams();
  const repository = useRepository(id);
  const status = useIndexStatus(id);
  const index = status.data;
  const percent = index && index.files_discovered > 0
    ? Math.min(100, Math.round(index.files_processed / index.files_discovered * 100))
    : 0;
  const stageIndex = index ? stageOrder.indexOf(index.state) : -1;

  return (
    <Shell title="Repository indexing">
      {repository.isPending && <p role="status" className="text-sm text-ink-secondary">Loading repository...</p>}
      {repository.isError && <ErrorNotice message={repository.error.message} onRetry={() => void repository.refetch()} />}
      {repository.data && <p className="mb-6 text-sm text-ink-secondary">{repository.data.name} / {repository.data.selected_branch}</p>}
      {status.isPending && <p role="status" className="text-sm text-ink-secondary">Loading index status...</p>}
      {status.isError && <ErrorNotice message={status.error.message} onRetry={() => void status.refetch()} />}

      {index && (
        <section className="panel max-w-2xl p-7">
          <div className="flex items-center justify-between">
            <IndexStateBadge state={index.state} />
            <span className="text-sm font-medium text-ink-secondary">{percent}%</span>
          </div>

          <div className="mt-5 h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full rounded-full bg-accent transition-all duration-500"
              style={{ width: `${index.state === "FAILED" ? 0 : Math.max(percent, 4)}%` }}
            />
          </div>
          <progress aria-label="Indexing progress" value={percent} max={100} className="sr-only" />

          {stageIndex >= 0 && index.state !== "FAILED" && (
            <ol className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
              {stageOrder.map((stage, i) => (
                <li key={stage} className={i <= stageIndex ? "text-ink-secondary" : ""}>{stage}</li>
              ))}
            </ol>
          )}

          <p className="mt-4 text-sm text-ink-secondary">{index.files_processed} of {index.files_discovered} files processed</p>
          {index.files_failed > 0 && <p className="mt-4 text-sm text-warning">{index.files_failed} files could not be indexed.</p>}
          {index.size_warning && <p className="mt-4 text-sm text-warning">This repository exceeds the tested 2,000-file scale. Retrieval quality and latency are untested at this size.</p>}
          {index.failure_reason && <div className="mt-4"><ErrorNotice message={index.failure_reason} /></div>}
          {index.state === "FAILED" && <p className="mt-5 text-sm text-ink-secondary">Retry is not available for this import yet.</p>}

          <div className="mt-6 flex items-center gap-5">
            {(index.state === "READY" || index.state === "PARTIAL") && (
              <Link to={`/repositories/${id}`} className="button-primary">
                Open workspace <ArrowRight size={15} strokeWidth={2} />
              </Link>
            )}
            <Link to="/dashboard" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-hover underline underline-offset-2">
              <ArrowLeft size={13} strokeWidth={2} /> Back to repositories
            </Link>
          </div>
        </section>
      )}
    </Shell>
  );
}
