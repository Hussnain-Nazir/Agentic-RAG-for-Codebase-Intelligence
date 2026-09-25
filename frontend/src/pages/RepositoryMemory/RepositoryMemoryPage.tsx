import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";

import { useRepositoryMemory, useResolvedEvidence } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";
import { ResolvedEvidence } from "../../components/common/ResolvedEvidence";

export function RepositoryMemoryPage() {
  const { id = "" } = useParams();
  const memory = useRepositoryMemory(id);
  const evidenceIds = useMemo(() => [...new Set(memory.data?.flatMap((item) => item.evidence_ids) ?? [])], [memory.data]);
  const resolved = useResolvedEvidence(id, evidenceIds);
  return <Shell title="Repository Memory">
    <Link className="text-sm text-cyan-300 underline" to={`/repositories/${id}`}>Back to workspace</Link>
    {memory.isPending && <div className="mt-6"><SkeletonList /></div>}
    {memory.isError && <div className="mt-6"><ErrorNotice message={memory.error.message} onRetry={() => void memory.refetch()} /></div>}
    {memory.data?.length === 0 && <p className="mt-6 text-slate-400">No repository memory has been saved.</p>}
    {evidenceIds.length > 0 && resolved.isPending && <p role="status" className="mt-4 text-sm">Loading evidence links...</p>}
    {resolved.isError && <div className="mt-4"><ErrorNotice message={resolved.error.message} onRetry={() => void resolved.refetch()} /></div>}
    <ul className="mt-6 space-y-4">{memory.data?.map((item) => <li key={item.id} className="panel">
      <div className="flex items-center gap-3"><h2 className="font-semibold">{item.topic}</h2>{item.is_stale && <span className="badge text-amber-300">Stale</span>}</div>
      <p className="mt-2 whitespace-pre-wrap text-sm">{item.content}</p>
      <p className="mt-3 text-xs text-slate-400">{item.type} · {item.confidence} · index version {item.repository_index_version}</p>
      {!resolved.isPending && !resolved.isError && <ResolvedEvidence repositoryId={id} ids={item.evidence_ids} links={resolved.data ?? []} />}
    </li>)}</ul>
  </Shell>;
}
