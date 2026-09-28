import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { authToken } from "../api/client";
import { conversationKey, writeConversation } from "../api/conversations";
import { Shell } from "../components/common/Shell";
import { FindingsPage } from "./Findings/FindingsPage";
import { RepositoryMemoryPage } from "./RepositoryMemory/RepositoryMemoryPage";

function mount(path: string, page: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    <Routes><Route path={path.replace("repo-1", ":id")} element={page} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

it("shows stale memory and resolves current evidence links", async () => {
  vi.spyOn(api, "memory").mockResolvedValue([{ id: "memory-1", repository_id: "repo-1", repository_index_version: 1, type: "FACT", scope: "repository", topic: "Login", content: "Login uses a token.", evidence_ids: ["chunk-1", "old-chunk"], confidence: "high", is_stale: true, source: "AUTO", created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z" }]);
  vi.spyOn(api, "resolveEvidence").mockResolvedValue([
    { evidence_id: "chunk-1", file_path: "auth/security.py", start_line: 10, end_line: 12, content_excerpt: "token" },
    { evidence_id: "old-chunk", file_path: null, start_line: null, end_line: null, content_excerpt: null },
  ]);
  mount("/repositories/repo-1/memory", <RepositoryMemoryPage />);
  expect(await screen.findByText("Stale")).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "auth/security.py:10-12" })).toHaveAttribute("href", "/repositories/repo-1/code?path=auth%2Fsecurity.py&start_line=10&end_line=12");
  expect(screen.getByText(/old-chun: no current index detail/)).toBeInTheDocument();
});

it("filters saved findings by type", async () => {
  vi.spyOn(api, "findings").mockResolvedValue([
    { id: "flow-1", repository_id: "repo-1", session_id: null, type: "FLOW_TRACE", title: "Login flow", content: { summary: "Flow summary" }, evidence_ids: [], created_at: "2026-09-25T10:00:00Z" },
    { id: "impact-1", repository_id: "repo-1", session_id: null, type: "IMPACT", title: "User impact", content: { requested_change: "Update User" }, evidence_ids: [], created_at: "2026-09-25T10:00:00Z" },
  ]);
  mount("/repositories/repo-1/findings", <FindingsPage />);
  expect(await screen.findByText("Login flow")).toBeInTheDocument();
  expect(screen.getByText("User impact")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Filter by type"), { target: { value: "IMPACT" } });
  expect(screen.queryByText("Login flow")).not.toBeInTheDocument();
  expect(screen.getByText("User impact")).toBeInTheDocument();
});

it("clears cached repository data when signing out", () => {
  const client = new QueryClient();
  client.setQueryData(["repositories"], [{ id: "private-repository" }]);
  authToken.set("test-token");
  render(<QueryClientProvider client={client}><MemoryRouter><Shell title="Settings">Content</Shell></MemoryRouter></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(authToken.get()).toBeNull();
  expect(client.getQueryData(["repositories"])).toBeUndefined();
});

it("removes every user's stored conversations on sign-out", () => {
  const userOne = "11111111-1111-4111-8111-111111111111";
  const userTwo = "22222222-2222-4222-8222-222222222222";
  const token = (subject: string) => `header.${btoa(JSON.stringify({ sub: subject }))}.signature`;
  const firstKey = conversationKey(token(userOne), "repo-1")!;
  const secondKey = conversationKey(token(userTwo), "repo-2")!;
  writeConversation(firstKey, [{ question: "first" }]);
  writeConversation(secondKey, [{ question: "second" }]);
  authToken.set(token(userOne));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><MemoryRouter><Shell title="Settings">Content</Shell></MemoryRouter></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(sessionStorage.getItem(firstKey)).toBeNull();
  expect(sessionStorage.getItem(secondKey)).toBeNull();
  expect(authToken.get()).toBeNull();
});
