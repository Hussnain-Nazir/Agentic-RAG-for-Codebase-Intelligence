import type { ReactNode } from "react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, FolderGit2, LogOut, PanelLeftClose, PanelLeftOpen, PlusSquare, Settings } from "lucide-react";

import { authToken } from "../../api/client";
import { clearAllConversations } from "../../api/conversations";
import { PrismLogo } from "./PrismLogo";

const navItems = [
  { to: "/dashboard", label: "Repositories", icon: FolderGit2 },
  { to: "/repositories/new", label: "Add repository", icon: PlusSquare },
];

function PrimarySidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const location = useLocation();

  function signOut() {
    clearAllConversations();
    authToken.clear();
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-surface-1 transition-[width] duration-150 ${collapsed ? "w-[68px]" : "w-[224px]"}`}
    >
      <div className="flex items-center justify-between gap-2 px-4 py-5">
        <Link to="/dashboard" className="flex min-w-0 items-center gap-2.5">
          <PrismLogo size={22} className="shrink-0" />
          {!collapsed && <span className="truncate text-[15px] font-semibold tracking-tight text-ink-primary">PRISM</span>}
        </Link>
        <button
          type="button"
          className="icon-button shrink-0"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen size={16} strokeWidth={1.75} /> : <PanelLeftClose size={16} strokeWidth={1.75} />}
        </button>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-2.5" aria-label="Primary">
        {navItems.map((item) => {
          const active = location.pathname === item.to || (item.to === "/dashboard" && location.pathname.startsWith("/repositories/") && location.pathname.split("/").length <= 3 && !location.pathname.includes("/new"));
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
        <Link
          to="/settings"
          title={collapsed ? "Settings" : undefined}
          className={`flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors duration-150 ${
            location.pathname === "/settings" ? "bg-accent-subtle text-ink-primary" : "text-ink-secondary hover:bg-surface-hover hover:text-ink-primary"
          }`}
        >
          <Settings size={17} strokeWidth={1.75} className="shrink-0" />
          {!collapsed && <span>Settings</span>}
        </Link>
        <div className="my-1 border-t border-border-subtle" />
        <button
          type="button"
          title={collapsed ? "Sign out" : undefined}
          className="flex items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm text-ink-secondary transition-colors duration-150 hover:bg-surface-hover hover:text-ink-primary"
          onClick={signOut}
        >
          <LogOut size={17} strokeWidth={1.75} className="shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </aside>
  );
}

export function Shell({ title, children, wide = false, bleed = false }: { title: string | null; children: ReactNode; wide?: boolean; bleed?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink-primary">
      <PrimarySidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} />
      <div className="min-w-0 flex-1 overflow-y-auto">
        <main className={`mx-auto flex h-full flex-col ${bleed ? "px-5 py-4" : "px-6 py-8 md:px-10"} ${wide ? "max-w-none" : "max-w-6xl"}`}>
          {title && <h1 className="mb-7 shrink-0 text-2xl font-semibold tracking-tight text-ink-primary">{title}</h1>}
          <div className="min-h-0 flex-1 animate-fade-in">{children}</div>
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
