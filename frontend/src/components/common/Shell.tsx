import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { authToken } from "../../api/client";

export function Shell({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-900/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link to="/dashboard" className="text-xl font-semibold tracking-tight text-white">Prism</Link>
          <nav className="flex items-center gap-5 text-sm">
            <Link to="/dashboard" className="text-slate-300 hover:text-white">Repositories</Link>
            <Link to="/repositories/new" className="text-slate-300 hover:text-white">Add repository</Link>
            <Link to="/settings" className="text-slate-300 hover:text-white">Settings</Link>
            <button type="button" className="text-slate-400 hover:text-white" onClick={() => {
              authToken.clear();
              queryClient.clear();
              navigate("/login", { replace: true });
            }}>Sign out</button>
          </nav>
        </div>
      </header>
      <main className={`mx-auto px-6 py-10 ${wide ? "max-w-[100rem]" : "max-w-6xl"}`}>
        <h1 className="mb-8 text-3xl font-semibold tracking-tight">{title}</h1>
        {children}
      </main>
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div role="alert" className="rounded-lg border border-rose-700 bg-rose-950/50 p-4 text-sm text-rose-100">
    <span>{message}</span>
    {onRetry && <button type="button" className="ml-4 underline" onClick={onRetry}>Retry</button>}
  </div>;
}

export function SkeletonList() {
  return <div aria-label="Loading repositories" className="space-y-4">
    {[1, 2, 3].map((item) => <div key={item} className="h-24 animate-pulse rounded-xl bg-slate-800" />)}
  </div>;
}
