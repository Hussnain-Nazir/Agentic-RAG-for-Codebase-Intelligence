import { Link } from "react-router-dom";
import { MapPin } from "lucide-react";

import type { ResolvedEvidenceLink } from "../../api/types";

export function ResolvedEvidence({ repositoryId, ids, links }: {
  repositoryId: string; ids: string[]; links: ResolvedEvidenceLink[];
}) {
  const byId = new Map(links.map((link) => [link.evidence_id, link]));
  return (
    <ul className="mt-3 flex flex-wrap gap-2 text-xs">
      {ids.map((id) => {
        const link = byId.get(id);
        if (!link?.file_path) return <li key={id} className="text-ink-disabled">Evidence {id.slice(0, 8)}: no current index detail</li>;
        const params = new URLSearchParams({ path: link.file_path });
        if (link.start_line !== null && link.end_line !== null) {
          params.set("start_line", String(link.start_line));
          params.set("end_line", String(link.end_line));
        }
        return (
          <li key={id}>
            <Link
              className="inline-flex items-center gap-1 rounded-full border border-border-strong bg-surface-3 px-2.5 py-1 font-mono text-accent-hover transition-colors duration-150 hover:border-accent-muted"
              to={`/repositories/${repositoryId}/code?${params}`}
            >
              <MapPin size={11} strokeWidth={2} />
              {link.file_path}:{link.start_line}-{link.end_line}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
