export type IndexState =
  | "PENDING" | "DISCOVERING" | "PARSING" | "EMBEDDING" | "INDEXING"
  | "READY" | "PARTIAL" | "FAILED";

export interface IndexSummary {
  id: string;
  version: number;
  revision: string;
  state: IndexState;
  files_discovered: number;
  files_processed: number;
  files_failed: number;
  size_warning: boolean;
  failure_reason: string | null;
}

export interface RepositorySummary {
  id: string;
  name: string;
  source_type: "github" | "upload";
  selected_branch: string;
  access_status: "ACTIVE" | "ACCESS_LOST" | "SOURCE_DELETED";
  index: IndexSummary | null;
}

export interface RepositoryDetail extends RepositorySummary {
  owner_id: string;
  github_repo_id: number | null;
  default_branch: string;
  created_at: string;
}

export interface IndexStatus extends Omit<IndexSummary, "id" | "revision"> {
  index_id: string;
}

export interface RepositoryImport {
  repository_id: string;
  index_id: string;
  state: IndexState;
  size_warning: boolean;
}

export interface GitHubInstallation {
  id: string;
  installation_id: number;
  account_login: string;
  status: "ACTIVE" | "REVOKED";
}

export interface GitHubRepository {
  id: number;
  name: string;
  full_name: string;
  default_branch: string;
  private: boolean;
}

export interface GitHubBranch { name: string }
