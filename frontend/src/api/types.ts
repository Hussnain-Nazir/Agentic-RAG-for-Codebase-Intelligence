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

export type ModelSlot = "A" | "B";
export interface ModelsConfig { model_a: { name: string | null }; model_b: { name: string | null } }

export interface FileTreeEntry {
  path: string; name: string; is_directory: boolean;
  language: string | null; status: string | null; size_bytes: number | null;
}
export interface CodeSymbol {
  id: string; file_path: string; name: string; symbol_type: string;
  start_line: number; end_line: number; match_type: string; score: number;
}
export interface FileContent {
  path: string; language: string | null; content: string;
  start_line: number; end_line: number; total_lines: number; truncated: boolean;
}
export interface Evidence {
  evidence_id: string; repository_id: string; repository_index_id: string;
  source_type: "CODE" | "DOCUMENTATION" | "WEB";
  file_path: string | null; symbol: string | null;
  start_line: number | null; end_line: number | null; content_excerpt: string;
  relationship_metadata: Record<string, unknown>;
  retrieval_metadata: Record<string, unknown>;
  external_source_metadata: Record<string, unknown> | null;
}
export interface RepositoryAnswer {
  answer: string; evidence: Evidence[]; confidence: "high" | "medium" | "low"; limitations: string | null;
}
export interface FlowStep {
  order: number; file: string; symbol: string; start_line: number; end_line: number;
  explanation: string; relationship_to_next: string | null; unresolved: boolean; evidence_ids: string[];
}
export interface FlowTraceResponse { summary: string; steps: FlowStep[]; evidence: Evidence[] }
export interface ImpactItem {
  file: string; symbol: string; reason: string; confidence: "high" | "medium" | "low";
  evidence_ids: string[]; recommended_action: string; tests_to_inspect: string[];
}
export interface ChangeImpactResponse {
  requested_change: string; directly_affected: ImpactItem[];
  likely_indirectly_affected: ImpactItem[]; evidence: Evidence[];
}
export interface ArchitectureResponse {
  agent_run_id: string; summary: string; languages: Record<string, number>;
  main_folders: string[]; frameworks_detected: string[]; entrypoints: string[];
  backend_boundary: string | null; frontend_boundary: string | null;
  database_layer: string | null; api_organization: string | null;
  auth_locations: string[]; test_locations: string[]; evidence: Evidence[];
}
export interface ModelResult {
  slot: ModelSlot; model_name: string; response: RepositoryAnswer | null;
  latency_ms: number; input_tokens: number | null; output_tokens: number | null;
  validation_status: string; error: string | null;
  schema_validation_status?: string | null;
  citation_total?: number | null; citation_accepted?: number | null; citation_rejected?: number | null;
  citation_rejection_reasons?: Record<string, number> | null;
}
export interface ModelComparisonResponse {
  agent_run_id: string; question: string; evidence_context_id: string; results: ModelResult[];
}
export interface RepositoryMemory {
  id: string; repository_id: string; repository_index_version: number;
  type: string; scope: string; topic: string; content: string;
  evidence_ids: string[]; confidence: string; is_stale: boolean;
  source: string; created_at: string; updated_at: string;
}
export interface Finding {
  id: string; repository_id: string; session_id: string | null;
  type: "FLOW_TRACE" | "IMPACT" | "REVIEW"; title: string;
  content: Record<string, unknown>; evidence_ids: string[]; created_at: string;
}
export interface ResolvedEvidenceLink {
  evidence_id: string; file_path: string | null; start_line: number | null;
  end_line: number | null; content_excerpt: string | null;
}
export interface AgentRunDetail {
  id: string; repository_id: string; session_id: string;
  task_type: string; status: string; started_at: string; completed_at: string | null;
}
export interface ToolCallDetail {
  id: string; sequence: number; tool_name: string; args_sanitized: Record<string, unknown>;
  status: string | null; duration_ms: number | null; result_summary: string | null;
  error: string | null; started_at: string; completed_at: string | null;
}
export interface ModelExecutionDetail {
  id: string; slot: ModelSlot; model_name: string; latency_ms: number;
  input_tokens: number | null; output_tokens: number | null;
  validation_status: string; error: string | null;
  schema_validation_status?: string | null;
  citation_total?: number | null; citation_accepted?: number | null; citation_rejected?: number | null;
  citation_rejection_reasons?: Record<string, number> | null;
}
export interface AgentTrace {
  run: AgentRunDetail; tool_calls: ToolCallDetail[]; model_executions: ModelExecutionDetail[];
}
