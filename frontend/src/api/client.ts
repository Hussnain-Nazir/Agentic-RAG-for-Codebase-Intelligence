import type {
  GitHubBranch, GitHubInstallation, GitHubRepository, IndexStatus,
  RepositoryDetail, RepositoryImport, RepositorySummary,
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
  return new ApiError(response.status, typeof detail === "string" ? detail : `Request failed (${response.status})`);
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
