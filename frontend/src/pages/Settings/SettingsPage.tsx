import { Link } from "react-router-dom";
import { Cpu, Github } from "lucide-react";

import { useInstallations, useInstallUrl, useModelsConfig } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";

export function SettingsPage() {
  const installations = useInstallations();
  const install = useInstallUrl();
  const models = useModelsConfig();

  async function reconnect() {
    try { window.location.assign((await install.mutateAsync()).url); }
    catch { /* Error is displayed below. */ }
  }

  return (
    <Shell title="Settings and Connections">
      <div className="max-w-2xl space-y-6">
        <section className="panel">
          <div className="panel-header">
            <h2 className="flex items-center gap-2 text-base font-medium text-ink-primary">
              <Cpu size={16} strokeWidth={1.75} className="text-ink-muted" /> Model Configuration
            </h2>
          </div>
          <div className="panel-body">
            <p className="text-sm text-ink-secondary">Model A and Model B are equal, independently configured peer slots.</p>
            {models.isPending && <p role="status" className="mt-4 text-sm text-ink-secondary">Loading model configuration...</p>}
            {models.isError && <div className="mt-4"><ErrorNotice message={models.error.message} onRetry={() => void models.refetch()} /></div>}
            {models.data && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {(["model_a", "model_b"] as const).map((key) => (
                  <div key={key} className="rounded-md border border-border-subtle bg-surface-1 p-4">
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{key === "model_a" ? "Model A" : "Model B"}</p>
                    <p className="mt-1.5 truncate font-mono text-sm text-ink-primary">{models.data[key].name ?? "Not configured"}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2 className="flex items-center gap-2 text-base font-medium text-ink-primary">
              <Github size={16} strokeWidth={1.75} className="text-ink-muted" /> GitHub App connections
            </h2>
          </div>
          <div className="panel-body">
            {installations.isPending && <SkeletonList />}
            {installations.isError && <ErrorNotice message={installations.error.message} onRetry={() => void installations.refetch()} />}
            {installations.data?.length === 0 && <p className="text-sm text-ink-secondary">No GitHub installation is connected.</p>}
            <ul className="space-y-2">
              {installations.data?.map((item) => (
                <li key={item.id} className="flex items-center justify-between rounded-md border border-border-subtle bg-surface-1 p-4">
                  <span className="text-sm text-ink-primary">{item.account_login}</span>
                  <span className="badge">{item.status}</span>
                </li>
              ))}
            </ul>
            <button type="button" className="button-primary mt-5" disabled={install.isPending} onClick={() => void reconnect()}>
              {install.isPending ? "Connecting..." : installations.data?.length ? "Reconnect GitHub" : "Connect GitHub"}
            </button>
            {install.isError && <div className="mt-4"><ErrorNotice message={install.error.message} /></div>}
            <p className="mt-5 text-sm">
              <Link className="font-medium text-accent-hover underline underline-offset-2" to="/repositories/new/github">Choose connected repository</Link>
            </p>
          </div>
        </section>
      </div>
    </Shell>
  );
}
