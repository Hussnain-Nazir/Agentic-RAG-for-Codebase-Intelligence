import { NavLink } from "react-router-dom";
import { BrainCircuit, ClipboardList, Code2, ListTree, MessageSquareText } from "lucide-react";

export function WorkspaceTabs({ repositoryId }: { repositoryId: string }) {
  const base = `/repositories/${repositoryId}`;
  const items = [
    { to: base, end: true, label: "Analyze", icon: MessageSquareText },
    { to: `${base}/code`, end: false, label: "Code", icon: Code2 },
    { to: `${base}/trace`, end: false, label: "Agent Trace", icon: ListTree },
    { to: `${base}/memory`, end: false, label: "Memory", icon: BrainCircuit },
    { to: `${base}/findings`, end: false, label: "Findings", icon: ClipboardList },
  ];
  return (
    <nav aria-label="Repository workspace" className="flex shrink-0 gap-1 border-b border-border-subtle px-1">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
              isActive ? "border-accent text-ink-primary" : "border-transparent text-ink-secondary hover:text-ink-primary"
            }`
          }
        >
          <item.icon size={15} strokeWidth={1.75} /> {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
