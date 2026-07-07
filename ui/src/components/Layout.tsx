import { AlertTriangle, BarChart3, Brain, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useApprovals, useHealth } from "../queries";

const NAV = [
  { to: "/", label: "Incidents", icon: AlertTriangle, end: true },
  { to: "/approvals", label: "Approvals", icon: ShieldCheck, end: false },
  { to: "/memory", label: "Memory", icon: Brain, end: false },
  { to: "/dashboard", label: "Dashboard", icon: BarChart3, end: false },
];

export default function Layout({ children }: { children: ReactNode }) {
  const pending = useApprovals("PENDING");
  const health = useHealth();
  const pendingCount = pending.data?.length ?? 0;
  const h = health.data;

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-ink-800 bg-ink-900">
        <div className="flex items-center gap-2 px-5 py-4">
          <span className="h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_12px] shadow-accent" />
          <span className="text-lg font-semibold tracking-tight text-ink-100">Argus</span>
          <span className="mt-1 text-[10px] uppercase tracking-widest text-ink-500">on-call</span>
        </div>

        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-accent/10 font-medium text-accent"
                    : "text-ink-400 hover:bg-ink-800 hover:text-ink-200"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              {label === "Approvals" && pendingCount > 0 && (
                <span className="rounded-full bg-amber-500 px-1.5 text-[11px] font-semibold text-ink-950">
                  {pendingCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-1.5 border-t border-ink-800 p-3 text-[11px] text-ink-500">
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${h?.db ? "bg-emerald-400" : "bg-rose-500"}`} />
            <span>{h ? (h.db ? "platform healthy" : "db unreachable") : "connecting…"}</span>
          </div>
          {h && (
            <>
              <div>
                LLM <span className="text-ink-300">{h.config.llm_mode}</span> ·{" "}
                {h.config.supervisor_model}
              </div>
              <div>memory {h.config.memory_enabled ? "on" : "off"}</div>
            </>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
