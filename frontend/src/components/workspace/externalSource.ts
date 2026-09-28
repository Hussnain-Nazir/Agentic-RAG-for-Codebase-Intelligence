import type { Evidence } from "../../api/types";

export function externalSource(item: Evidence): { title: string; urlText: string | null; href: string | null } | null {
  if (item.source_type !== "WEB") return null;
  const metadata = item.external_source_metadata;
  const title = typeof metadata?.title === "string" && metadata.title.trim()
    ? metadata.title : "External source";
  const urlText = typeof metadata?.url === "string" && metadata.url.trim()
    ? metadata.url : null;
  let href: string | null = null;
  if (urlText) {
    try {
      const parsed = new URL(urlText);
      if (parsed.protocol === "https:" || parsed.protocol === "http:") href = parsed.href;
    } catch { /* Keep an invalid URL as inert text. */ }
  }
  return { title, urlText, href };
}
