import type {
  AgentTrace, ArchitectureResponse, ChangeImpactResponse, CodeSymbol, FileContent,
  FileTreeEntry, Finding, FlowTraceResponse, GitHubBranch, GitHubInstallation,
  GitHubRepository, IndexStatus, ModelComparisonResponse, ModelSlot, ModelsConfig,
  RepositoryAnswer, RepositoryDetail, RepositoryImport, RepositoryMemory,
  RepositorySummary, ResolvedEvidenceLink,
} from "./types";

const TOKEN_KEY = "prism_access_token";
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export const authToken = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

async function parseError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null;
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail
    : detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string"
      ? detail.message : `Request failed (${response.status})`;
  return new ApiError(response.status, message);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const token = authToken.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) throw await parseError(response);
  return response.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) };
}

export const api = {
  register: (email: string, password: string) =>
    request<{ user_id: string }>("/auth/register", json("POST", { email, password })),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", json("POST", { email, password })),
  installUrl: () => request<{ url: string }>("/github/install-url"),
  installations: () => request<GitHubInstallation[]>("/github/installations"),
  installationRepositories: (installationId: string) =>
    request<GitHubRepository[]>(`/github/installations/${encodeURIComponent(installationId)}/repositories`),
  branches: (installationId: string, repositoryId: number) =>
    request<GitHubBranch[]>(`/github/installations/${encodeURIComponent(installationId)}/repositories/${repositoryId}/branches`),
  createGitHubRepository: (repositoryId: number, branch: string) =>
    request<RepositoryImport>("/repositories", json("POST", {
      source_type: "github", github_repo_id: repositoryId, branch,
    })),
  repositories: () => request<RepositorySummary[]>("/repositories"),
  repository: (id: string) => request<RepositoryDetail>(`/repositories/${encodeURIComponent(id)}`),
  indexStatus: (id: string) => request<IndexStatus>(`/repositories/${encodeURIComponent(id)}/index-status`),
  modelsConfig: () => request<ModelsConfig>("/models/config"),
  files: (id: string, path = "") => request<FileTreeEntry[]>(`/repositories/${encodeURIComponent(id)}/files${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  symbols: (id: string, query: string) => request<CodeSymbol[]>(`/repositories/${encodeURIComponent(id)}/symbols?q=${encodeURIComponent(query)}`),
  fileContent: (id: string, path: string, startLine?: number, endLine?: number) => {
    const params = new URLSearchParams({ path });
    if (startLine !== undefined && endLine !== undefined) {
      params.set("start_line", String(startLine));
      params.set("end_line", String(endLine));
    }
    return request<FileContent>(`/repositories/${encodeURIComponent(id)}/files/content?${params}`);
  },
  ask: (id: string, question: string, modelSlot: ModelSlot) => request<{ agent_run_id: string; answer: RepositoryAnswer }>(
    `/repositories/${encodeURIComponent(id)}/ask`, json("POST", { question, model_slot: modelSlot })),
  flowTrace: (id: string, question: string, modelSlot: ModelSlot) => request<{ agent_run_id: string; trace: FlowTraceResponse }>(
    `/repositories/${encodeURIComponent(id)}/flow-trace`, json("POST", { question, model_slot: modelSlot })),
  changeImpact: (id: string, changeDescription: string, modelSlot: ModelSlot) => request<{ agent_run_id: string; impact: ChangeImpactResponse }>(
    `/repositories/${encodeURIComponent(id)}/change-impact`, json("POST", { change_description: changeDescription, model_slot: modelSlot })),
  architecture: (id: string, modelSlot: ModelSlot) => request<ArchitectureResponse>(
    `/repositories/${encodeURIComponent(id)}/architecture?model_slot=${modelSlot}`),
  compareModels: (id: string, question: string) => request<ModelComparisonResponse>(
    `/repositories/${encodeURIComponent(id)}/compare-models`, json("POST", { question })),
  memory: (id: string) => request<RepositoryMemory[]>(`/repositories/${encodeURIComponent(id)}/memory?include_stale=true`),
  findings: (id: string) => request<Finding[]>(`/repositories/${encodeURIComponent(id)}/findings`),
  saveFinding: (id: string, type: "FLOW_TRACE" | "IMPACT", content: Record<string, unknown>, evidenceIds: string[]) => request<Finding>(
    `/repositories/${encodeURIComponent(id)}/findings`, json("POST", { type, content, evidence_ids: evidenceIds })),
  resolveEvidence: (id: string, evidenceIds: string[]) => {
    const params = new URLSearchParams();
    evidenceIds.forEach((item) => params.append("ids", item));
    return request<ResolvedEvidenceLink[]>(`/repositories/${encodeURIComponent(id)}/evidence?${params}`);
  },
  agentTrace: (runId: string) => request<AgentTrace>(`/agent-runs/${encodeURIComponent(runId)}/trace`),
};

export function uploadRepository(file: File, onProgress: (percent: number) => void): Promise<RepositoryImport> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/repositories`);
    const token = authToken.get();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new Error("Upload failed. Check the connection and retry."));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText) as RepositoryImport); }
        catch { reject(new Error("The server returned an invalid response.")); }
        return;
      }
      let message = `Upload failed (${xhr.status})`;
      try {
        const body = JSON.parse(xhr.responseText) as { detail?: unknown };
        if (typeof body.detail === "string") message = body.detail;
      } catch { /* Keep the status message. */ }
      reject(new ApiError(xhr.status, message));
    };
    const form = new FormData();
    form.append("upload", file);
    xhr.send(form);
  });
}
