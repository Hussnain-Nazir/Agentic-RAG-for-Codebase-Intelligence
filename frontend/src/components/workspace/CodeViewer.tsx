import { useState } from "react";
import { Check, Copy } from "lucide-react";

const KEYWORDS = new Set([
  "function", "return", "const", "let", "var", "if", "else", "for", "while", "class", "extends",
  "import", "export", "from", "default", "async", "await", "try", "catch", "finally", "new",
  "this", "super", "interface", "type", "implements", "public", "private", "protected", "static",
  "def", "elif", "except", "with", "as", "pass", "lambda", "yield", "raise", "None", "True", "False",
  "self", "in", "is", "not", "and", "or", "None",
]);

function highlight(line: string) {
  const tokens: { text: string; kind: "keyword" | "string" | "comment" | "number" | "plain" }[] = [];
  const pattern = /(#.*$|\/\/.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(line))) {
    if (match.index > lastIndex) tokens.push({ text: line.slice(lastIndex, match.index), kind: "plain" });
    if (match[1]) tokens.push({ text: match[1], kind: "comment" });
    else if (match[2]) tokens.push({ text: match[2], kind: "string" });
    else if (match[3]) tokens.push({ text: match[3], kind: "number" });
    else if (match[4]) tokens.push({ text: match[4], kind: KEYWORDS.has(match[4]) ? "keyword" : "plain" });
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < line.length) tokens.push({ text: line.slice(lastIndex), kind: "plain" });
  return tokens;
}

const tokenClass: Record<string, string> = {
  keyword: "text-accent-hover",
  string: "text-success",
  comment: "text-ink-muted italic",
  number: "text-warning",
  plain: "text-ink-primary",
};

export function CodeViewer({ path, content, startLine, highlightStart, highlightEnd, fill = false }: {
  path: string; content: string; startLine: number; highlightStart?: number | null; highlightEnd?: number | null; fill?: boolean;
}) {
  const [copied, setCopied] = useState<"path" | "code" | null>(null);
  const lines = content.split("\n");

  async function copy(kind: "path" | "code", text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      setTimeout(() => setCopied(null), 1200);
    } catch { /* Clipboard may be unavailable; the button simply has no effect. */ }
  }

  return (
    <div className={fill ? "code-surface flex h-full flex-col overflow-hidden" : "code-surface overflow-hidden"}>
      <div className="sticky top-0 flex shrink-0 items-center justify-between gap-3 border-b border-border bg-surface-2 px-3 py-2 font-sans">
        <span className="truncate text-xs text-ink-secondary">{path}</span>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" className="icon-button" title="Copy path" onClick={() => void copy("path", path)}>
            {copied === "path" ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.75} />}
          </button>
          <button type="button" className="icon-button" title="Copy code" onClick={() => void copy("code", content)}>
            {copied === "code" ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.75} />}
          </button>
        </div>
      </div>
      <div className={fill ? "min-h-0 flex-1 overflow-auto" : "max-h-[26rem] overflow-auto"}>
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, index) => {
              const lineNumber = startLine + index;
              const isHighlighted = highlightStart != null && highlightEnd != null && lineNumber >= highlightStart && lineNumber <= highlightEnd;
              return (
                <tr key={lineNumber} className={isHighlighted ? "bg-accent-subtle" : undefined}>
                  <td className="select-none whitespace-nowrap py-0.5 pl-3 pr-3 text-right align-top text-ink-disabled">{lineNumber}</td>
                  <td className="w-full whitespace-pre py-0.5 pr-4 align-top">
                    {highlight(line).map((token, tokenIndex) => (
                      <span key={tokenIndex} className={tokenClass[token.kind]}>{token.text}</span>
                    ))}
                    {line.length === 0 && "\u00A0"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
