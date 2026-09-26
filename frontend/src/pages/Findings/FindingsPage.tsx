import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ClipboardList } from "lucide-react";

import { useFindings, useResolvedEvidence } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";
import { EmptyState } from "../../components/common/EmptyState";
import { ResolvedEvidence } from "../../components/common/ResolvedEvidence";

export function FindingsPage() {
  const { id = "" } = useParams();
  const [filter, setFilter] = useState("all");
  const findings = useFindings(id);
  const evidenceIds = useMemo(() => [...new Set(findings.data?.flatMap((item) => item.evidence_ids) ?? [])], [findings.data]);
  const resolved = useResolvedEvidence(id, evidenceIds);
  const filtered = findings.data?.filter((item) => filter === "all" || item.type === filter) ?? [];

  return (
    <Shell title="Saved Findings">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Link className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-hover underline underline-offset-2" to={`/repositories/${id}`}>
          <ArrowLeft size={13} strokeWidth={2} /> Back to workspace
        </Link>
        <div>
          <label className="label" htmlFor="finding-filter">Filter by type</label>
          <select id="finding-filter" className="input" value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">All</option><option value="FLOW_TRACE">Flow Trace</option><option value="IMPACT">Impact</option><option value="REVIEW">Review</option>
          </select>
        </div>
      </div>

      {findings.isPending && <div className="mt-6"><SkeletonList /></div>}
      {findings.isError && <div className="mt-6"><ErrorNotice message={findings.error.message} onRetry={() => void findings.refetch()} /></div>}
      {findings.data && filtered.length === 0 && (
        <div className="mt-6">
          <EmptyState icon={<ClipboardList size={18} strokeWidth={1.75} />} title="No findings match this filter." />
        </div>
      )}
      {evidenceIds.length > 0 && resolved.isPending && <p role="status" className="mt-4 text-sm text-ink-secondary">Loading evidence links...</p>}
      {resolved.isError && <div className="mt-4"><ErrorNotice message={resolved.error.message} onRetry={() => void resolved.refetch()} /></div>}

      <ul className="mt-6 space-y-4">
        {filtered.map((item) => (
          <li key={item.id} className="panel p-5">
            <div className="flex items-center gap-3">
              <h2 className="font-medium text-ink-primary">{item.title}</h2>
              <span className="badge">{item.type}</span>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink-secondary">
              {typeof item.content.summary === "string" ? item.content.summary : typeof item.content.requested_change === "string" ? item.content.requested_change : "Saved analysis"}
            </p>
            <p className="mt-3 text-xs text-ink-muted">Saved {new Date(item.created_at).toLocaleString()}</p>
            {!resolved.isPending && !resolved.isError && <ResolvedEvidence repositoryId={id} ids={item.evidence_ids} links={resolved.data ?? []} />}
          </li>
        ))}
      </ul>
    </Shell>
  );
}
