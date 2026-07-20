import { FlaskConical } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReactNode } from "react";
import { EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { StatusChip } from "../components/StatusChip";
import { money, pct, seconds } from "../lib/format";
import type { DashboardSummary, EvalRunSummary } from "../api";
import { useDashboard, useEvalRuns } from "../queries";

const TOOLTIP = {
  contentStyle: {
    background: "#ffffff",
    border: "1px solid #e3e8f0",
    borderRadius: 8,
    fontSize: 12,
    boxShadow: "0 4px 12px rgba(15, 23, 42, 0.08)",
  },
  labelStyle: { color: "#2e3c53" },
};

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wide text-ink-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink-100">{value}</div>
      {sub && <div className="text-xs text-ink-500">{sub}</div>}
    </div>
  );
}

function evalMemory(r: EvalRunSummary): string {
  if (r.config?.ablation === "memory") return r.config.condition ?? "?";
  return r.config?.memory_enabled ? "on" : "off";
}

function EvalPanel({ runs }: { runs: EvalRunSummary[] }) {
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={<FlaskConical className="h-7 w-7" />}
        title="No eval runs yet"
        hint="Run the evaluation harness (python -m argus.evals.run) to populate suite scores and the memory-lift ablation here."
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-800 text-left text-xs uppercase tracking-wide text-ink-500">
            <th className="py-2 pr-4 font-medium">Suite</th>
            <th className="py-2 pr-4 font-medium">When</th>
            <th className="py-2 pr-4 font-medium">Memory</th>
            <th className="py-2 pr-4 font-medium">Supervisor</th>
            <th className="py-2 text-right font-medium">Pass rate</th>
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, 8).map((r) => {
            const rate = r.cases ? Math.round((100 * r.passes) / r.cases) : 0;
            return (
              <tr key={r.id} className="border-b border-ink-800/60">
                <td className="py-2 pr-4 font-medium text-ink-100">{r.suite}</td>
                <td className="py-2 pr-4 text-ink-500">{(r.started_at ?? "").slice(0, 10)}</td>
                <td className="py-2 pr-4">
                  <span className="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-ink-300">
                    {evalMemory(r)}
                  </span>
                </td>
                <td className="py-2 pr-4 text-ink-400">{r.config?.supervisor_model ?? "—"}</td>
                <td className="py-2 text-right tabular-nums text-ink-200">
                  {r.passes}/{r.cases}
                  {r.cases ? ` · ${rate}%` : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The API returns one row per (role, model) pair, but this chart is labelled *by role* — so
 *  after a model re-route the same role rendered as several identically-labelled bars
 *  ("supervisor" x3). Fold them back to one bar per role, biggest first. */
function tokensByRole(rows: DashboardSummary["cost_by_role"]) {
  const acc = new Map<string, { role: string; tokens_in: number; tokens_out: number }>();
  for (const r of rows) {
    const cur = acc.get(r.role) ?? { role: r.role, tokens_in: 0, tokens_out: 0 };
    cur.tokens_in += r.tokens_in;
    cur.tokens_out += r.tokens_out;
    acc.set(r.role, cur);
  }
  return [...acc.values()].sort(
    (a, b) => b.tokens_in + b.tokens_out - (a.tokens_in + a.tokens_out),
  );
}

export default function Dashboard() {
  const { data, isLoading, error } = useDashboard();
  const evals = useEvalRuns();

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="System health, cost, and outcomes" />
      <div className="space-y-6 p-6">
        {error && <ErrorNote error={error} />}
        {isLoading && !data && <Spinner label="Crunching aggregates…" />}
        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Stat label="Incidents" value={data.total_incidents} />
              <Stat label="Resolution rate" value={pct(data.resolution_rate)} sub="resolved / total" />
              <Stat label="Escalation rate" value={pct(data.escalation_rate)} sub="needed a human" />
              <Stat label="Median MTTR" value={seconds(data.median_mttr_s ?? null)} sub={`avg ${seconds(data.avg_mttr_s ?? null)}`} />
              <Stat label="Total cost" value={money(data.total_cost_usd)} sub={`${(data.total_tokens_in + data.total_tokens_out).toLocaleString()} tok`} />
            </div>

            <div className="card p-4">
              <div className="mb-3 text-xs uppercase tracking-wide text-ink-500">Incidents by status</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.incidents_by_status)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => (
                    <div key={status} className="flex items-center gap-1.5">
                      <StatusChip status={status} />
                      <span className="text-sm tabular-nums text-ink-300">{count}</span>
                    </div>
                  ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="card p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-ink-500">
                  Cost per incident (last 20)
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={data.cost_per_incident.map((c) => ({ ...c, usd: c.cost_usd }))}>
                    <CartesianGrid stroke="#e3e8f0" vertical={false} />
                    <XAxis dataKey="service" hide />
                    <YAxis tick={{ fill: "#5b6b84", fontSize: 11 }} width={48} tickFormatter={(v) => `$${v}`} />
                    <Tooltip {...TOOLTIP} formatter={(v: any) => money(Number(v))} />
                    <Bar dataKey="usd" radius={[3, 3, 0, 0]}>
                      {data.cost_per_incident.map((c) => (
                        <Cell key={c.incident_id} fill={c.status === "RESOLVED" ? "#10b981" : "#3b82f6"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="card p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-ink-500">Tokens by role</div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={tokensByRole(data.cost_by_role)}>
                    <CartesianGrid stroke="#e3e8f0" vertical={false} />
                    <XAxis dataKey="role" tick={{ fill: "#5b6b84", fontSize: 10 }} angle={-20} textAnchor="end" height={50} interval={0} />
                    <YAxis
                      tick={{ fill: "#5b6b84", fontSize: 11 }}
                      width={40}
                      tickFormatter={(v: number) =>
                        v >= 1_000_000
                          ? `${Number((v / 1_000_000).toFixed(1))}M`
                          : v >= 1000
                            ? `${Math.round(v / 1000)}k`
                            : `${v}`
                      }
                    />
                    <Tooltip {...TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="tokens_in" stackId="t" fill="#3b82f6" name="in" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="tokens_out" stackId="t" fill="#8b5cf6" name="out" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card p-4">
              <div className="mb-2 text-xs uppercase tracking-wide text-ink-500">Evaluation</div>
              {evals.data ? <EvalPanel runs={evals.data} /> : <Spinner label="Loading eval runs…" />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
