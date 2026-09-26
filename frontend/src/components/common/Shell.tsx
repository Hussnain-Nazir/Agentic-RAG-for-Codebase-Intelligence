import type { ReactNode } from "react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, ChevronsLeft, ChevronsRight, FolderGit2, LogOut, PlusSquare, Settings } from "lucide-react";

import { authToken } from "../../api/client";
import { PrismLogo } from "./PrismLogo";

const navItems = [
  { to: "/dashboard", label: "Repositories", icon: FolderGit2 },
  { to: "/repositories/new", label: "Add repository", icon: PlusSquare },
  { to: "/settings", label: "Settings", icon: Settings },
];

function PrimarySidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const location = useLocation();

  function signOut() {
    authToken.clear();
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-surface-1 transition-[width] duration-150 ${collapsed ? "w-[68px]" : "w-[224px]"}`}
    >
      <Link to="/dashboard" className="flex items-center gap-2.5 px-4 py-5">
        <PrismLogo size={22} />
        {!collapsed && <span className="text-[15px] font-semibold tracking-tight text-ink-primary">PRISM</span>}
      </Link>
      <nav className="flex flex-1 flex-col gap-0.5 px-2.5" aria-label="Primary">
        {navItems.map((item) => {
          const active = location.pathname === item.to || (item.to === "/dashboard" && location.pathname.startsWith("/repositories/") && location.pathname.split("/").length <= 2);
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              title={collapsed ? item.label : undefined}
              className={`flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors duration-150 ${
                active ? "bg-accent-subtle text-ink-primary" : "text-ink-secondary hover:bg-surface-hover hover:text-ink-primary"
              }`}
            >
              <Icon size={17} strokeWidth={1.75} className="shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>
      <div className="flex flex-col gap-0.5 border-t border-border-subtle px-2.5 py-2.5">
        <button
          type="button"
          title={collapsed ? "Sign out" : undefined}
          className="flex items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm text-ink-secondary transition-colors duration-150 hover:bg-surface-hover hover:text-ink-primary"
          onClick={signOut}
        >
          <LogOut size={17} strokeWidth={1.75} className="shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        <button
          type="button"
          className="flex items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm text-ink-muted transition-colors duration-150 hover:bg-surface-hover hover:text-ink-primary"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronsRight size={17} strokeWidth={1.75} /> : <ChevronsLeft size={17} strokeWidth={1.75} />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}

export function Shell({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="flex min-h-screen bg-canvas text-ink-primary">
      <PrimarySidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="min-w-0 flex-1">
        <main className={`mx-auto px-6 py-8 md:px-10 ${wide ? "max-w-none" : "max-w-6xl"}`}>
          <h1 className="mb-7 text-2xl font-semibold tracking-tight text-ink-primary">{title}</h1>
          <div className="animate-fade-in">{children}</div>
        </main>
      </div>
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger-subtle px-4 py-3 text-sm text-ink-primary">
      <AlertTriangle size={16} strokeWidth={1.75} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <span>{message}</span>
        {onRetry && (
          <button type="button" className="ml-3 font-medium text-accent-hover underline underline-offset-2" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function SkeletonList() {
  return (
    <div aria-label="Loading repositories" className="space-y-3">
      {[1, 2, 3].map((item) => <div key={item} className="skeleton h-24 rounded-lg" />)}
    </div>
  );
}
