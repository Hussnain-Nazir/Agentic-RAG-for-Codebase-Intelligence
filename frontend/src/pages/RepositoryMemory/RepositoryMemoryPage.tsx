import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { BrainCircuit } from "lucide-react";

import { useRepositoryMemory, useResolvedEvidence } from "../../api/hooks";
import { ErrorNotice, SkeletonList } from "../../components/common/Shell";
import { EmptyState } from "../../components/common/EmptyState";
import { ResolvedEvidence } from "../../components/common/ResolvedEvidence";

export function RepositoryMemoryPage() {
  const params = useParams();
  const id = params.id ?? "";
  const memory = useRepositoryMemory(id);
  const evidenceIds = useMemo(() => [...new Set(memory.data?.flatMap((item) => item.evidence_ids) ?? [])], [memory.data]);
  const resolved = useResolvedEvidence(id, evidenceIds);

  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto py-2">
      {memory.isPending && <SkeletonList />}
      {memory.isError && <ErrorNotice message={memory.error.message} onRetry={() => void memory.refetch()} />}
      {memory.data?.length === 0 && (
        <EmptyState icon={<BrainCircuit size={18} strokeWidth={1.75} />} title="No repository memory has been saved." />
      )}
      {evidenceIds.length > 0 && resolved.isPending && <p role="status" className="mb-4 text-sm text-ink-secondary">Loading evidence links...</p>}
      {resolved.isError && <div className="mb-4"><ErrorNotice message={resolved.error.message} onRetry={() => void resolved.refetch()} /></div>}

      <ul className="space-y-4">
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
    </div>
  );
}
