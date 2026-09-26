import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BrainCircuit } from "lucide-react";

import { useRepositoryMemory, useResolvedEvidence } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";
import { EmptyState } from "../../components/common/EmptyState";
import { ResolvedEvidence } from "../../components/common/ResolvedEvidence";

export function RepositoryMemoryPage() {
  const { id = "" } = useParams();
  const memory = useRepositoryMemory(id);
  const evidenceIds = useMemo(() => [...new Set(memory.data?.flatMap((item) => item.evidence_ids) ?? [])], [memory.data]);
  const resolved = useResolvedEvidence(id, evidenceIds);

  return (
    <Shell title="Repository Memory">
      <Link className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-accent-hover underline underline-offset-2" to={`/repositories/${id}`}>
        <ArrowLeft size={13} strokeWidth={2} /> Back to workspace
      </Link>

      {memory.isPending && <div className="mt-6"><SkeletonList /></div>}
      {memory.isError && <div className="mt-6"><ErrorNotice message={memory.error.message} onRetry={() => void memory.refetch()} /></div>}
      {memory.data?.length === 0 && (
        <div className="mt-6">
          <EmptyState icon={<BrainCircuit size={18} strokeWidth={1.75} />} title="No repository memory has been saved." />
        </div>
      )}
      {evidenceIds.length > 0 && resolved.isPending && <p role="status" className="mt-4 text-sm text-ink-secondary">Loading evidence links...</p>}
      {resolved.isError && <div className="mt-4"><ErrorNotice message={resolved.error.message} onRetry={() => void resolved.refetch()} /></div>}

      <ul className="mt-6 space-y-4">
        {memory.data?.map((item) => (
          <li key={item.id} className="panel p-5">
            <div className="flex items-center gap-3">
              <h2 className="font-medium text-ink-primary">{item.topic}</h2>
              {item.is_stale && <span className="badge text-warning">Stale</span>}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink-secondary">{item.content}</p>
            <p className="mt-3 text-xs text-ink-muted">{item.type} · {item.confidence} · index version {item.repository_index_version}</p>
            {!resolved.isPending && !resolved.isError && <ResolvedEvidence repositoryId={id} ids={item.evidence_ids} links={resolved.data ?? []} />}
          </li>
        ))}
      </ul>
    </Shell>
  );
}
