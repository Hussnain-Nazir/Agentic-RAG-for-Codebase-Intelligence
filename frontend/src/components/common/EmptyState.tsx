import type { ReactNode } from "react";

export function EmptyState({ icon, title, description, action }: {
  icon?: ReactNode; title: string; description?: string; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border-strong bg-surface-1 px-8 py-14 text-center">
      {icon && <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-surface-2 text-ink-muted">{icon}</div>}
      <h2 className="text-base font-medium text-ink-primary">{title}</h2>
      {description && <p className="mt-2 max-w-sm text-sm text-ink-secondary">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
