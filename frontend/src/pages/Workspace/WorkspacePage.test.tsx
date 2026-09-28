import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, authToken } from "../../api/client";
import { conversationKey, writeConversation } from "../../api/conversations";
import type { Evidence, ModelSlot } from "../../api/types";
import { AgentTrace } from "../../components/workspace/AgentTrace";
import { AnalysisWorkspace } from "../../components/workspace/AnalysisWorkspace";
import type { AnalysisMode, AnalysisView } from "../../components/workspace/AnalysisWorkspace";
import { EvidencePanel } from "../../components/workspace/EvidencePanel";
import { RepositoryTree } from "../../components/workspace/RepositoryTree";
import type { FileSelection } from "../../components/workspace/RepositoryTree";
import { AnalyzeTab } from "./AnalyzeTab";
import { CodeTab } from "./CodeTab";
import { TraceTab } from "./TraceTab";
import { WorkspacePage } from "./WorkspacePage";
import { RepositoryMemoryPage } from "../RepositoryMemory/RepositoryMemoryPage";
import { FindingsPage } from "../Findings/FindingsPage";

const FIRST_USER = "11111111-1111-4111-8111-111111111111";
const SECOND_USER = "22222222-2222-4222-8222-222222222222";
function tokenFor(userId: string) { return `header.${btoa(JSON.stringify({ sub: userId }))}.signature`; }

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

function AnalysisHarness({ initialMode = "ask", repositoryId = "repo-1" }: { initialMode?: AnalysisMode; repositoryId?: string }) {
  const [mode, setMode] = useState<AnalysisMode>(initialMode);
  const [view, setView] = useState<AnalysisView | null>(null);
  return <AnalysisWorkspace repositoryId={repositoryId} modelSlot={"A" as ModelSlot} mode={mode} onModeChange={setMode} view={view} onResult={setView} />;
}

function mountWorkspaceRoutes() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/repositories/repo-1"]}>
    <Routes><Route path="/repositories/:id" element={<WorkspacePage />}>
      <Route index element={<AnalyzeTab />} />
      <Route path="code" element={<CodeTab />} />
      <Route path="trace" element={<TraceTab />} />
      <Route path="memory" element={<RepositoryMemoryPage />} />
      <Route path="findings" element={<FindingsPage />} />
    </Route></Routes>
  </MemoryRouter></QueryClientProvider>);
}

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("analysis workspace", () => {
  it("keeps the conversation through Code, Agent Trace, Memory, and Findings tab visits", async () => {
    authToken.set(tokenFor(FIRST_USER));
    vi.spyOn(api, "repository").mockResolvedValue({ id: "repo-1", name: "Fixture", source_type: "upload", selected_branch: "upload", access_status: "ACTIVE", index: null, owner_id: FIRST_USER, github_repo_id: null, default_branch: "upload", created_at: "2026-09-25T10:00:00Z" });
    vi.spyOn(api, "modelsConfig").mockResolvedValue({ model_a: { name: "model-a" }, model_b: { name: "model-b" } });
    vi.spyOn(api, "files").mockResolvedValue([]);
    vi.spyOn(api, "memory").mockResolvedValue([]);
    vi.spyOn(api, "findings").mockResolvedValue([]);
    vi.spyOn(api, "agentTrace").mockResolvedValue({
      run: { id: "run-1", repository_id: "repo-1", session_id: "session-1", task_type: "REPOSITORY_QA", status: "OK", started_at: "2026-09-25T10:00:00Z", completed_at: "2026-09-25T10:00:01Z" },
      tool_calls: [], model_executions: [],
    });
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: { answer: "Tabbed answer", evidence: [], confidence: "low", limitations: null } });
    mountWorkspaceRoutes();
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Tabbed question" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Tabbed answer")).toBeInTheDocument();
    const workspaceNav = screen.getByRole("navigation", { name: "Repository workspace" });
    for (const tab of ["Code", "Agent Trace", "Memory", "Findings"]) {
      fireEvent.click(within(workspaceNav).getByRole("link", { name: tab }));
      fireEvent.click(within(workspaceNav).getByRole("link", { name: "Analyze" }));
      expect(screen.getByText("Tabbed question")).toBeInTheDocument();
      expect(screen.getByText("Tabbed answer")).toBeInTheDocument();
    }
    expect(api.ask).toHaveBeenCalledTimes(1);
  });

  it("keeps prior turns visible when switching among all four analysis modes", async () => {
    authToken.set(tokenFor(FIRST_USER));
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: { answer: "Stored answer", evidence: [evidence], confidence: "high", limitations: null } });
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Where is login?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Stored answer")).toBeInTheDocument();
    for (const tab of ["Flow Trace", "Change Impact", "Architecture", "Codebase Q&A"]) {
      fireEvent.click(screen.getByRole("tab", { name: tab }));
      expect(screen.getByText("Where is login?")).toBeInTheDocument();
      expect(screen.getByText("Stored answer")).toBeInTheDocument();
    }
  });

  it("restores Q&A and Q&A comparison turns after an Analyze remount", async () => {
    authToken.set(tokenFor(FIRST_USER));
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: { answer: "Stored Q&A", evidence: [evidence], confidence: "high", limitations: null } });
    vi.spyOn(api, "compareModels").mockResolvedValue({
      agent_run_id: "run-2", question: "Compare login", evidence_context_id: "ctx-1",
      results: [
        { slot: "A", model_name: "model-a", response: { answer: "Stored A", evidence: [evidence], confidence: "high", limitations: null }, latency_ms: 10, input_tokens: 20, output_tokens: 30, validation_status: "VALID", error: null },
        { slot: "B", model_name: "model-b", response: { answer: "Stored B", evidence: [evidence], confidence: "medium", limitations: null }, latency_ms: 11, input_tokens: 21, output_tokens: 31, validation_status: "VALID", error: null },
      ],
    });
    const first = mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Explain login" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Stored Q&A")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Compare login" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask & Compare" }));
    expect(await screen.findByText("Stored A")).toBeInTheDocument();
    expect(screen.getByText("Stored B")).toBeInTheDocument();
    expect(sessionStorage.getItem(conversationKey(authToken.get(), "repo-1")!)).toContain("Stored B");
    first.unmount();
    mount(<AnalysisHarness />);
    expect(screen.getByText("Explain login")).toBeInTheDocument();
    expect(screen.getByText("Stored Q&A")).toBeInTheDocument();
    expect(screen.getByText("Compare login")).toBeInTheDocument();
    expect(screen.getByText("Stored A")).toBeInTheDocument();
    expect(screen.getByText("Stored B")).toBeInTheDocument();
    expect(api.ask).toHaveBeenCalledTimes(1);
    expect(api.compareModels).toHaveBeenCalledTimes(1);
  });

  it("isolates stored turns by repository and authenticated user", async () => {
    authToken.set(tokenFor(FIRST_USER));
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: { answer: "Private answer", evidence: [], confidence: "low", limitations: null } });
    const first = mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Private question" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Private answer")).toBeInTheDocument();
    first.unmount();
    const secondRepository = mount(<AnalysisHarness repositoryId="repo-2" />);
    expect(screen.queryByText("Private answer")).not.toBeInTheDocument();
    secondRepository.unmount();
    authToken.set(tokenFor(SECOND_USER));
    const secondUser = mount(<AnalysisHarness />);
    expect(screen.queryByText("Private answer")).not.toBeInTheDocument();
    secondUser.unmount();
    authToken.set(tokenFor(FIRST_USER));
    mount(<AnalysisHarness />);
    expect(screen.getByText("Private answer")).toBeInTheDocument();
  });

  it("removes both visible and stored turns only when Clear Conversation is pressed", async () => {
    authToken.set(tokenFor(FIRST_USER));
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: { answer: "Clearable answer", evidence: [], confidence: "low", limitations: null } });
    const first = mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Clearable question" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Clearable answer")).toBeInTheDocument();
    const key = conversationKey(authToken.get(), "repo-1")!;
    expect(sessionStorage.getItem(key)).toContain("Clearable answer");
    fireEvent.click(screen.getByRole("button", { name: "Clear Conversation" }));
    expect(screen.queryByText("Clearable answer")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(key)).toBeNull();
    first.unmount();
    mount(<AnalysisHarness />);
    expect(screen.queryByText("Clearable answer")).not.toBeInTheDocument();
  });

  it("guards oversized or unavailable session storage without breaking the composer", () => {
    authToken.set(tokenFor(FIRST_USER));
    const key = conversationKey(authToken.get(), "repo-1")!;
    expect(writeConversation(key, [{ question: "x".repeat(1_100_000) }])).toBe(false);
    expect(sessionStorage.getItem(key)).toBeNull();
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("quota", "QuotaExceededError"); });
    expect(writeConversation(key, [{ question: "small" }])).toBe(false);
    setItem.mockRestore();
    mount(<AnalysisHarness />);
    expect(screen.getByLabelText("Question")).toBeInTheDocument();
  });

  it.each([
    ["ask", "Codebase Q&A", "Question", "Ask"],
    ["flow", "Flow Trace", "Question", "Ask"],
    ["impact", "Change Impact", "Describe the proposed change", "Ask"],
    ["compare", "Codebase Q&A", "Question", "Ask & Compare"],
  ] as const)("clears the %s draft on send and keeps a failed question in its turn", async (kind, tab, label, button) => {
    let rejectRequest!: (reason?: unknown) => void;
    const pending = new Promise<never>((_, reject) => { rejectRequest = reject; });
    if (kind === "ask") vi.spyOn(api, "ask").mockReturnValue(pending);
    if (kind === "flow") vi.spyOn(api, "flowTrace").mockReturnValue(pending);
    if (kind === "impact") vi.spyOn(api, "changeImpact").mockReturnValue(pending);
    if (kind === "compare") vi.spyOn(api, "compareModels").mockReturnValue(pending);
    mount(<AnalysisHarness />);
    if (kind === "flow" || kind === "impact") fireEvent.click(screen.getByRole("tab", { name: tab }));
    const input = screen.getByLabelText(label) as HTMLTextAreaElement;
    const question = `Investigate ${kind} submission`;
    fireEvent.change(input, { target: { value: question } });
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(input).toHaveValue("");
    expect(within(screen.getByTestId("conversation-turn")).getByText(question)).toBeInTheDocument();
    expect(within(screen.getByTestId("conversation-turn")).getByText("Gathering evidence and validating the result...")).toBeInTheDocument();
    rejectRequest(new Error("Selected request failed"));
    expect(await within(screen.getByTestId("conversation-turn")).findByText("Selected request failed")).toBeInTheDocument();
    expect(within(screen.getByTestId("conversation-turn")).getByText(question)).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it.each([
    ["ask", "Codebase Q&A", "Answer cleared"],
    ["flow", "Flow Trace", "Flow cleared"],
    ["impact", "Change Impact", "Requested change: Impact cleared"],
    ["architecture", "Architecture", "Architecture cleared"],
  ] as const)("clears the shared client-side conversation in %s mode", async (mode, tabLabel, resultText) => {
    const ask = vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-ask", answer: { answer: "Answer cleared", evidence: [], confidence: "low", limitations: null } });
    const flow = vi.spyOn(api, "flowTrace").mockResolvedValue({ agent_run_id: "run-flow", trace: { summary: "Flow cleared", steps: [], evidence: [] } });
    const impact = vi.spyOn(api, "changeImpact").mockResolvedValue({ agent_run_id: "run-impact", impact: { requested_change: "Impact cleared", directly_affected: [], likely_indirectly_affected: [], evidence: [] } });
    const architecture = vi.spyOn(api, "architecture").mockResolvedValue({ agent_run_id: "run-architecture", summary: "Architecture cleared", languages: {}, main_folders: [], frameworks_detected: [], entrypoints: [], backend_boundary: null, frontend_boundary: null, database_layer: null, api_organization: null, auth_locations: [], test_locations: [], evidence: [] });
    mount(<AnalysisHarness />);
    if (mode !== "ask") fireEvent.click(screen.getByRole("tab", { name: tabLabel }));
    if (mode !== "architecture") fireEvent.change(screen.getByLabelText(mode === "impact" ? "Describe the proposed change" : "Question"), { target: { value: "Clear this request" } });
    fireEvent.click(screen.getByRole("button", { name: mode === "architecture" ? "Explain architecture" : "Ask" }));
    expect(await screen.findByText(resultText)).toBeInTheDocument();
    const callsBefore = [ask, flow, impact, architecture].reduce((sum, spy) => sum + spy.mock.calls.length, 0);
    fireEvent.click(screen.getByRole("button", { name: "Clear Conversation" }));
    expect(screen.queryByText(resultText)).not.toBeInTheDocument();
    expect(screen.getByText("Ask anything about this repository.")).toBeInTheDocument();
    expect([ask, flow, impact, architecture].reduce((sum, spy) => sum + spy.mock.calls.length, 0)).toBe(callsBefore);
    if (mode !== "architecture") expect(screen.getByLabelText(mode === "impact" ? "Describe the proposed change" : "Question")).toHaveValue("");
  });
  it("renders a grounded Ask response", async () => {
    vi.spyOn(api, "ask").mockResolvedValue({ agent_run_id: "run-1", answer: {
      answer: "Login issues a token.", evidence: [evidence], confidence: "high", limitations: null,
    } });
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How does login work?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
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
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How does login work?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask & Compare" }));
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
    expect(screen.getByText("Ask anything about this repository.")).toBeInTheDocument();
  });

  it("shows analysis loading and error in its own panel", async () => {
    let fail!: (reason: Error) => void;
    vi.spyOn(api, "ask").mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
    mount(<AnalysisHarness />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Where is login?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
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
