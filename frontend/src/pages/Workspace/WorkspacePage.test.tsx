import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { Evidence, ModelSlot } from "../../api/types";
import { AgentTrace } from "../../components/workspace/AgentTrace";
import { AnalysisWorkspace } from "../../components/workspace/AnalysisWorkspace";
import type { AnalysisMode, AnalysisView } from "../../components/workspace/AnalysisWorkspace";
import { EvidencePanel } from "../../components/workspace/EvidencePanel";
import { RepositoryTree } from "../../components/workspace/RepositoryTree";
import type { FileSelection } from "../../components/workspace/RepositoryTree";

const evidence: Evidence = {
  evidence_id: "evidence-1", repository_id: "repo-1", repository_index_id: "index-1",
  source_type: "CODE", file_path: "auth/security.py", symbol: "create_token",
  start_line: 10, end_line: 12, content_excerpt: "def create_token(): pass",
  relationship_metadata: {}, retrieval_metadata: { source_chunk_ids: ["chunk-1"] }, external_source_metadata: null,
};

function mount(element: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{element}</MemoryRouter></QueryClientProvider>);
}

function AnalysisHarness({ initialMode = "ask" }: { initialMode?: AnalysisMode }) {
  const [mode, setMode] = useState<AnalysisMode>(initialMode);
  const [view, setView] = useState<AnalysisView | null>(null);
  return <AnalysisWorkspace repositoryId="repo-1" modelSlot={"A" as ModelSlot} mode={mode} onModeChange={setMode} view={view} onResult={setView} />;
}

afterEach(() => vi.restoreAllMocks());

describe("analysis workspace", () => {
  it("renders a grounded Ask response", async () => {
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: {
      answer: "Login issues a token.", evidence: [evidence], confidence: "high", limitations: null,
    } });
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How does login work?" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("Login issues a token.")).toBeInTheDocument();
    expect(screen.getByText("Confidence: high")).toBeInTheDocument();
    expect(api.ask).toHaveBeenCalledWith("repo-1", "How does login work?", "A");
  });

  it("renders Flow Trace steps in order and marks unresolved links", async () => {
    vi.spyOn(api, "flowTrace").mockResolvedValue({ agent_run_id: "run-2", trace: {
      summary: "Login flow", evidence: [evidence], steps: [
        { order: 2, file: "auth/security.py", symbol: "create_token", start_line: 10, end_line: 12, explanation: "Creates token.", relationship_to_next: null, unresolved: true, evidence_ids: ["evidence-1"] },
        { order: 1, file: "routers/auth.py", symbol: "login", start_line: 1, end_line: 4, explanation: "Handles login.", relationship_to_next: "CALLS", unresolved: false, evidence_ids: ["evidence-1"] },
      ],
    } });
    mount(<AnalysisHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "Flow Trace" }));
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Trace login" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("Login flow")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText("1. login")).toBeInTheDocument();
    expect(within(items[1]).getByText("2. create_token")).toBeInTheDocument();
    expect(screen.getByText("Unresolved transition")).toBeInTheDocument();
  });

  it("separates direct and indirect change impacts", async () => {
    const save = vi.spyOn(api, "saveFinding").mockResolvedValue({
      id: "finding-1", repository_id: "repo-1", session_id: null, type: "IMPACT",
      title: "Impact", content: {}, evidence_ids: ["chunk-1"], created_at: "2026-09-25T10:00:00Z",
    });
    vi.spyOn(api, "changeImpact").mockResolvedValue({ agent_run_id: "run-3", impact: {
      requested_change: "Change User organizations", evidence: [evidence],
      directly_affected: [{ file: "models/user.py", symbol: "User", reason: "Relation changes.", confidence: "high", evidence_ids: ["evidence-1"], recommended_action: "Update model", tests_to_inspect: ["test_user.py"] }],
      likely_indirectly_affected: [{ file: "routers/users.py", symbol: "list_users", reason: "Reads users.", confidence: "medium", evidence_ids: ["evidence-1"], recommended_action: "Review filter", tests_to_inspect: [] }],
    } });
    mount(<AnalysisHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "Change Impact" }));
    fireEvent.change(screen.getByLabelText("Describe the proposed change"), { target: { value: "Change User organizations" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("Directly affected")).toBeInTheDocument();
    expect(screen.getByText("Likely indirectly affected")).toBeInTheDocument();
    expect(screen.getByText("Relation changes.")).toBeInTheDocument();
    expect(screen.getByText("Reads users.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Finding" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save Finding" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("repo-1", "IMPACT", expect.objectContaining({ requested_change: "Change User organizations" }), ["chunk-1"]));
  });

  it("renders deterministic Architecture response fields", async () => {
    vi.spyOn(api, "architecture").mockResolvedValue({
      agent_run_id: "run-4", summary: "A FastAPI service.", languages: { python: 6 }, main_folders: ["auth"],
      frameworks_detected: ["FastAPI"], entrypoints: ["main.py"], backend_boundary: "backend",
      frontend_boundary: null, database_layer: "db.py", api_organization: "routers",
      auth_locations: ["auth/security.py"], test_locations: ["tests"], evidence: [],
    });
    mount(<AnalysisHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "Architecture" }));
    fireEvent.click(screen.getByRole("button", { name: "Explain architecture" }));
    expect(await screen.findByText("A FastAPI service.")).toBeInTheDocument();
    expect(screen.getByText("python: 6")).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
  });

  it("renders two comparison results and no winner indicator", async () => {
    vi.spyOn(api, "compareModels").mockResolvedValue({
      agent_run_id: "run-5", question: "How does login work?", evidence_context_id: "context-1",
      results: [
        { slot: "A", model_name: "model-a", response: { answer: "Answer A", evidence: [evidence], confidence: "high", limitations: null }, latency_ms: 10, input_tokens: 20, output_tokens: 30, validation_status: "VALID", error: null },
        { slot: "B", model_name: "model-b", response: { answer: "Answer B", evidence: [evidence], confidence: "medium", limitations: null }, latency_ms: 12, input_tokens: 22, output_tokens: 32, validation_status: "VALID", error: null },
      ],
    });
    mount(<AnalysisHarness initialMode="compare" />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How does login work?" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare Models" }));
    expect(await screen.findByText("Answer A")).toBeInTheDocument();
    expect(screen.getByText("Answer B")).toBeInTheDocument();
    expect(screen.getByText(/20 input tokens/)).toBeInTheDocument();
    expect(screen.queryByText(/winner|ranking|best model/i)).not.toBeInTheDocument();
  });
});

describe("independent panels", () => {
  it("opens the selected evidence file at the cited range", async () => {
    vi.spyOn(api, "fileContent").mockResolvedValue({ path: "auth/security.py", language: "python", content: "def create_token(): pass", start_line: 10, end_line: 12, total_lines: 30, truncated: false });
    function Harness() {
      const [selected, setSelected] = useState<FileSelection | null>(null);
      return <EvidencePanel repositoryId="repo-1" evidence={[evidence]} selected={selected} onSelect={setSelected} />;
    }
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /auth\/security.py:10-12/ }));
    await waitFor(() => expect(api.fileContent).toHaveBeenCalledWith("repo-1", "auth/security.py", 10, 12));
    expect(await screen.findByText("def create_token(): pass")).toBeInTheDocument();
  });

  it("renders trace tool calls and model executions in API order", async () => {
    vi.spyOn(api, "agentTrace").mockResolvedValue({
      run: { id: "run-1", repository_id: "repo-1", session_id: "session-1", task_type: "FLOW_TRACE", status: "OK", started_at: "2026-09-25T10:00:00Z", completed_at: "2026-09-25T10:00:02Z" },
      tool_calls: [
        { id: "tool-1", sequence: 1, tool_name: "search_codebase", args_sanitized: {}, status: "OK", duration_ms: 4, result_summary: "12 chunks", error: null, started_at: "2026-09-25T10:00:00Z", completed_at: "2026-09-25T10:00:01Z" },
        { id: "tool-2", sequence: 2, tool_name: "find_symbol", args_sanitized: {}, status: "OK", duration_ms: 5, result_summary: "1 symbol", error: null, started_at: "2026-09-25T10:00:01Z", completed_at: "2026-09-25T10:00:02Z" },
      ],
      model_executions: [
        { id: "model-1", slot: "A", model_name: "model-a", latency_ms: 10, input_tokens: 20, output_tokens: 30, validation_status: "VALID", error: null },
        { id: "model-2", slot: "B", model_name: "model-b", latency_ms: 12, input_tokens: 22, output_tokens: 32, validation_status: "VALID", error: null },
      ],
    });
    mount(<AgentTrace runId="run-1" />);
    expect(await screen.findByText(/Searched repository/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    const details = screen.getAllByText(/#\d/).map((item) => item.textContent);
    expect(details[0]).toContain("#1 search_codebase");
    expect(details[1]).toContain("#2 find_symbol");
    const modelDetails = screen.getAllByText(/Model [AB]: model-/).map((item) => item.textContent);
    expect(modelDetails[0]).toContain("Model A: model-a");
    expect(modelDetails[1]).toContain("Model B: model-b");
  });

  it("keeps tree and evidence loading and empty states separate", async () => {
    vi.spyOn(api, "files").mockResolvedValue([]);
    mount(<div><RepositoryTree repositoryId="repo-1" onSelect={() => {}} /><EvidencePanel repositoryId="repo-1" evidence={[]} selected={null} onSelect={() => {}} /></div>);
    expect(screen.getByText("Citations will appear after an analysis.")).toBeInTheDocument();
    expect(await screen.findByText("No files in this view.")).toBeInTheDocument();
    expect(screen.getByText("Select evidence or a file to inspect it.")).toBeInTheDocument();
  });

  it("shows a tree error without replacing the analysis empty state", async () => {
    vi.spyOn(api, "files").mockRejectedValue(new Error("File tree unavailable"));
    mount(<div><RepositoryTree repositoryId="repo-1" onSelect={() => {}} /><AnalysisHarness /></div>);
    expect(await screen.findByText("File tree unavailable")).toBeInTheDocument();
    expect(screen.getByText("Ask a question to get started.")).toBeInTheDocument();
  });

  it("shows analysis loading and error in its own panel", async () => {
    let fail!: (reason: Error) => void;
    vi.spyOn(api, "ask").mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Where is login?" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("Gathering evidence and validating the result...")).toBeInTheDocument();
    fail(new Error("Analysis unavailable"));
    expect(await screen.findByText("Analysis unavailable")).toBeInTheDocument();
  });

  it("shows file viewer error without hiding citations", async () => {
    vi.spyOn(api, "fileContent").mockRejectedValue(new Error("File unavailable"));
    mount(<EvidencePanel repositoryId="repo-1" evidence={[evidence]} selected={{ path: "auth/security.py", startLine: 10, endLine: 12 }} onSelect={() => {}} />);
    expect(await screen.findByText("File unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /auth\/security.py:10-12/ })).toBeInTheDocument();
  });

  it("shows trace loading and error in the trace drawer", async () => {
    let fail!: (reason: Error) => void;
    vi.spyOn(api, "agentTrace").mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
    mount(<AgentTrace runId="run-1" />);
    expect(screen.getByText("Loading trace...")).toBeInTheDocument();
    fail(new Error("Trace unavailable"));
    expect(await screen.findByText("Trace unavailable")).toBeInTheDocument();
  });
});
