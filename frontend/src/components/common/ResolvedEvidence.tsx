import { Link } from "react-router-dom";

import type { ResolvedEvidenceLink } from "../../api/types";

export function ResolvedEvidence({ repositoryId, ids, links }: {
  repositoryId: string; ids: string[]; links: ResolvedEvidenceLink[];
}) {
  const byId = new Map(links.map((link) => [link.evidence_id, link]));
  return <ul className="mt-3 space-y-1 text-xs">{ids.map((id) => {
    const link = byId.get(id);
    if (!link?.file_path) return <li key={id} className="text-slate-500">Evidence {id.slice(0, 8)}: no current index detail</li>;
    const params = new URLSearchParams({ path: link.file_path });
    if (link.start_line !== null && link.end_line !== null) {
      params.set("start_line", String(link.start_line));
      params.set("end_line", String(link.end_line));
    }
    return <li key={id}><Link className="break-all text-cyan-300 underline" to={`/repositories/${repositoryId}?${params}`}>
      {link.file_path}:{link.start_line}-{link.end_line}
    </Link></li>;
  })}</ul>;
}
