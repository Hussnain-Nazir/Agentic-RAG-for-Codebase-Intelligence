import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import * as apiClient from "../api/client";
import { AddRepositoryPage, MAX_ZIP_BYTES } from "./AddRepository/AddRepositoryPage";
import { LoginPage, RegisterPage } from "./Authentication/AuthPages";
import { DashboardPage } from "./Dashboard/DashboardPage";

function renderPage(page: ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    <Routes><Route path={path} element={page} /><Route path="/dashboard" element={<p>Dashboard arrived</p>} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("authentication", () => {
  it.each(["login", "register"] as const)("toggles password visibility on %s without a request", (mode) => {
    const login = vi.spyOn(api, "login");
    const register = vi.spyOn(api, "register");
    renderPage(mode === "login" ? <LoginPage /> : <RegisterPage />, `/${mode}`);
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    fireEvent.change(password, { target: { value: "test-password-123" } });
    expect(password.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password.type).toBe("text");
    expect(password.value).toBe("test-password-123");
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password.type).toBe("password");
    expect(login).not.toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
  });

  it("validates login and stores a token after a successful response", async () => {
    const login = vi.spyOn(api, "login").mockResolvedValue({ access_token: "test-token" });
    renderPage(<LoginPage />, "/login");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Dashboard arrived")).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("user@example.com", "password123");
    expect(sessionStorage.getItem("prism_access_token")).toBe("test-token");
  });

  it("validates registration and signs in after account creation", async () => {
    const register = vi.spyOn(api, "register").mockResolvedValue({ user_id: "user-id" });
    const login = vi.spyOn(api, "login").mockResolvedValue({ access_token: "registered-token" });
    renderPage(<RegisterPage />, "/register");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Use at least 8 characters")).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Dashboard arrived")).toBeInTheDocument();
    expect(register).toHaveBeenCalledWith("user@example.com", "long-password");
    expect(login).toHaveBeenCalledWith("user@example.com", "long-password");
  });
});

describe("dashboard", () => {
  it("shows loading, empty, and populated repository states", async () => {
    let finish!: (value: Awaited<ReturnType<typeof api.repositories>>) => void;
    vi.spyOn(api, "repositories").mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce([{
        id: "repo-id", name: "Fixture", source_type: "upload", selected_branch: "upload", access_status: "ACTIVE",
        index: { id: "index-id", version: 1, revision: "hash", state: "READY", files_discovered: 1, files_processed: 1, files_failed: 0, size_warning: false, failure_reason: null },
      }]);
    const first = renderPage(<DashboardPage />, "/dashboard");
    expect(screen.getByLabelText("Loading repositories")).toBeInTheDocument();
    finish([]);
    expect(await screen.findByText("Add your first repository.")).toBeInTheDocument();
    first.unmount();
    renderPage(<DashboardPage />, "/dashboard");
    expect(await screen.findByText("Fixture")).toBeInTheDocument();
    expect(screen.getByText("ZIP upload")).toBeInTheDocument();
    expect(screen.getByText("READY")).toBeInTheDocument();
  });
});

describe("ZIP upload", () => {
  it("rejects archives over 200 MB before any request", async () => {
    const upload = vi.spyOn(apiClient, "uploadRepository");
    renderPage(<AddRepositoryPage />, "/repositories/new");
    const file = new File(["zip"], "large.zip", { type: "application/zip" });
    Object.defineProperty(file, "size", { value: MAX_ZIP_BYTES + 1 });
    fireEvent.change(screen.getByLabelText("ZIP archive"), { target: { files: [file] } });
    expect(await screen.findByText("ZIP archives must be 200 MB or smaller.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload repository" })).toBeDisabled();
    await waitFor(() => expect(upload).not.toHaveBeenCalled());
  });
});
