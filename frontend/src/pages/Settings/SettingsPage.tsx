import { Link } from "react-router-dom";

import { useInstallations, useInstallUrl } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";

export function SettingsPage() {
  const installations = useInstallations();
  const install = useInstallUrl();
  async function reconnect() {
    try { window.location.assign((await install.mutateAsync()).url); }
    catch { /* Error is displayed below. */ }
  }
  return <Shell title="Settings and Connections">
    <section className="panel max-w-2xl">
      <h2 className="text-xl font-semibold">GitHub App connections</h2>
      {installations.isPending && <div className="mt-5"><SkeletonList /></div>}
      {installations.isError && <div className="mt-5"><ErrorNotice message={installations.error.message} onRetry={() => void installations.refetch()} /></div>}
      {installations.data?.length === 0 && <p className="mt-5 text-sm text-slate-400">No GitHub installation is connected.</p>}
      <ul className="mt-5 space-y-3">{installations.data?.map((item) => <li key={item.id} className="flex items-center justify-between rounded-lg border border-slate-700 p-4">
        <span>{item.account_login}</span><span className="badge">{item.status}</span>
      </li>)}</ul>
      <button type="button" className="button-primary mt-6" disabled={install.isPending} onClick={() => void reconnect()}>{install.isPending ? "Connecting..." : installations.data?.length ? "Reconnect GitHub" : "Connect GitHub"}</button>
      {install.isError && <div className="mt-4"><ErrorNotice message={install.error.message} /></div>}
      <p className="mt-5 text-sm"><Link className="text-cyan-300 underline" to="/repositories/new/github">Choose connected repository</Link></p>
    </section>
  </Shell>;
}
