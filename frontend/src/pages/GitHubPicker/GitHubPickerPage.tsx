import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Lock, Search } from "lucide-react";

import { useBranches, useCreateGitHubRepository, useInstallationRepositories, useInstallations } from "../../api/hooks";
import { ErrorNotice, Shell, SkeletonList } from "../../components/common/Shell";

export function GitHubPickerPage() {
  const navigate = useNavigate();
  const installations = useInstallations();
  const [installationId, setInstallationId] = useState<string | null>(null);
  const [repositoryId, setRepositoryId] = useState<number | null>(null);
  const [branch, setBranch] = useState("");
  const [search, setSearch] = useState("");
  const [visibility, setVisibility] = useState("all");
  const repositories = useInstallationRepositories(installationId);
  const branches = useBranches(installationId, repositoryId);
  const importer = useCreateGitHubRepository();
  const activeInstallations = installations.data?.filter((item) => item.status === "ACTIVE") ?? [];

  useEffect(() => {
    if (!installationId && activeInstallations.length) {
      setInstallationId(activeInstallations[0].id);
    }
  }, [installationId, installations.data]);

  const selectedRepository = repositories.data?.find((item) => item.id === repositoryId);
  useEffect(() => {
    if (selectedRepository) setBranch(selectedRepository.default_branch);
  }, [selectedRepository?.id, selectedRepository?.default_branch]);

  const filtered = useMemo(() => (repositories.data ?? []).filter((item) => {
    const matchesSearch = item.full_name.toLowerCase().includes(search.toLowerCase());
    const matchesVisibility = visibility === "all" || (visibility === "private" ? item.private : !item.private);
    return matchesSearch && matchesVisibility;
  }), [repositories.data, search, visibility]);

  async function importSelected() {
    if (!repositoryId || !branch) return;
    try {
      const result = await importer.mutateAsync({ repositoryId, branch });
      navigate(`/repositories/${result.repository_id}/indexing`);
    } catch { /* Mutation state displays the error. */ }
  }

  return (
    <Shell title="Choose GitHub repository">
      {installations.isPending && <p role="status" className="text-sm text-ink-secondary">Loading installations...</p>}
      {installations.isError && <ErrorNotice message={installations.error.message} onRetry={() => void installations.refetch()} />}
      {installations.data && activeInstallations.length === 0 && (
        <div className="panel p-8">
          <p className="text-sm text-ink-secondary">No authorized repositories. Adjust your GitHub App installation.</p>
          <Link className="mt-4 inline-block text-sm font-medium text-accent-hover underline underline-offset-2" to="/repositories/new">Connect GitHub</Link>
        </div>
      )}
      {activeInstallations.length > 0 && <>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label htmlFor="installation" className="label">Installation</label>
            <select id="installation" className="input" value={installationId ?? ""} onChange={(event) => {
              setInstallationId(event.target.value); setRepositoryId(null); setBranch("");
            }}>
              {activeInstallations.map((item) => <option key={item.id} value={item.id}>{item.account_login}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="repository-search" className="label">Search repositories</label>
            <div className="relative">
              <Search size={15} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input id="repository-search" className="input pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Owner or repository name" />
            </div>
          </div>
          <div>
            <label htmlFor="visibility" className="label">Visibility</label>
            <select id="visibility" className="input" value={visibility} onChange={(event) => setVisibility(event.target.value)}>
              <option value="all">All</option><option value="public">Public</option><option value="private">Private</option>
            </select>
          </div>
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-[1fr_20rem]">
          <div>
            {repositories.isPending && <SkeletonList />}
            {repositories.isError && <ErrorNotice message={repositories.error.message} onRetry={() => void repositories.refetch()} />}
            {repositories.data && filtered.length === 0 && <p className="rounded-lg border border-border bg-surface-1 p-6 text-sm text-ink-secondary">No repositories match this filter.</p>}
            <div className="space-y-2">{filtered.map((item) => (
              <button
                type="button"
                key={item.id}
                onClick={() => setRepositoryId(item.id)}
                className={`flex w-full items-center justify-between gap-3 rounded-lg border p-4 text-left transition-colors duration-150 ${
                  repositoryId === item.id ? "border-accent bg-accent-subtle" : "border-border bg-surface-1 hover:border-border-strong"
                }`}
              >
                <span className="truncate font-medium text-ink-primary">{item.full_name}</span>
                <span className="badge shrink-0">{item.private && <Lock size={10} strokeWidth={2} />}{item.private ? "Private" : "Public"}</span>
              </button>
            ))}</div>
          </div>
          <aside className="panel p-6">
            <h2 className="font-medium text-ink-primary">Import selection</h2>
            {!selectedRepository && <p className="mt-3 text-sm text-ink-secondary">Select a repository to choose its branch.</p>}
            {selectedRepository && <>
              <p className="mt-3 text-sm text-ink-primary">{selectedRepository.full_name}</p>
              <label htmlFor="branch" className="label mt-5">Branch</label>
              <select id="branch" className="input" value={branch} onChange={(event) => setBranch(event.target.value)} disabled={branches.isPending || branches.isError}>
                <option value={selectedRepository.default_branch}>{selectedRepository.default_branch}</option>
                {branches.data?.filter((item) => item.name !== selectedRepository.default_branch).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
              </select>
              {branches.isError && <div className="mt-3"><ErrorNotice message={branches.error.message} onRetry={() => void branches.refetch()} /></div>}
              <button type="button" className="button-primary mt-6 w-full" disabled={!branch || branches.isPending || branches.isError || importer.isPending} onClick={() => void importSelected()}>
                {importer.isPending ? "Importing..." : "Import"}
              </button>
              {importer.isError && <div className="mt-3"><ErrorNotice message={importer.error.message} /></div>}
            </>}
          </aside>
        </div>
      </>}
    </Shell>
  );
}
