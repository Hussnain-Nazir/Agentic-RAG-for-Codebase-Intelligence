import type { IndexState } from "../../api/types";

const stateStyles: Record<IndexState, string> = {
  PENDING: "text-ink-secondary border-border-strong",
  DISCOVERING: "text-accent-hover border-accent-muted",
  PARSING: "text-accent-hover border-accent-muted",
  EMBEDDING: "text-accent-hover border-accent-muted",
  INDEXING: "text-accent-hover border-accent-muted",
  READY: "text-success border-success/40",
  PARTIAL: "text-warning border-warning/40",
  FAILED: "text-danger border-danger/40",
};

const activeStates: IndexState[] = ["DISCOVERING", "PARSING", "EMBEDDING", "INDEXING"];

export function IndexStateBadge({ state }: { state: IndexState }) {
  return (
    <span className={`badge ${stateStyles[state]}`}>
      <span className={`badge-dot ${activeStates.includes(state) ? "animate-pulse-soft" : ""}`} />
      {state}
    </span>
  );
}
