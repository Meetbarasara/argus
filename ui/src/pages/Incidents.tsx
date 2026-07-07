import { Brain, ChevronRight, Inbox, Zap } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LevelBadge, SeverityBadge, StatusChip } from "../components/StatusChip";
import { EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { money, timeAgo } from "../lib/format";
import { useIncidents } from "../queries";

const FILTERS: { label: string; value?: string }[] = [
  { label: "All" },
  { label: "Investigating", value: "INVESTIGATING" },
  { label: "Waiting", value: "WAITING_APPROVAL" },
  { label: "Resolved", value: "RESOLVED" },
  { label: "Taken over", value: "TAKEN_OVER" },
];

export default function Incidents() {
  const [status, setStatus] = useState<string | undefined>(undefined);
  const nav = useNavigate();
  const { data, isLoading, error } = useIncidents(status);

  return (
    <div>
      <PageHeader
        title="Incidents"
        subtitle="Live feed — newest first, refreshing every 2s"
        right={
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setStatus(f.value)}
                className={status === f.value ? "btn-primary" : "btn-ghost"}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      />
      <div className="p-6">
        {error && <ErrorNote error={error} />}
        {isLoading && !data && <Spinner label="Loading incidents…" />}
        {data && data.length === 0 && (
          <EmptyState
            icon={<Inbox className="h-8 w-8" />}
            title="No incidents"
            hint="A quiet system. Inject a fault in the demo world and it will appear here within seconds."
          />
        )}
        {data && data.length > 0 && (
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-800 text-left text-xs uppercase tracking-wide text-ink-500">
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Incident</th>
                  <th className="px-4 py-2.5 font-medium">Escalation</th>
                  <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                  <th className="px-4 py-2.5 text-right font-medium">Age</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.map((inc) => {
                  const attention = inc.status === "WAITING_APPROVAL";
                  return (
                    <tr
                      key={inc.id}
                      onClick={() => nav(`/incidents/${inc.id}`)}
                      className={`group cursor-pointer border-b border-ink-800/60 transition-colors hover:bg-ink-800/40 ${
                        attention ? "bg-amber-500/[0.04]" : ""
                      }`}
                    >
                      <td
                        className={`px-4 py-3 ${
                          attention ? "border-l-2 border-amber-400" : "border-l-2 border-transparent"
                        }`}
                      >
                        <StatusChip status={inc.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-ink-100">{inc.title}</span>
                          <SeverityBadge severity={inc.severity} />
                          {inc.memory_used && (
                            <span title="memory recalled">
                              <Brain className="h-3.5 w-3.5 text-violet-400" />
                            </span>
                          )}
                          {inc.fast_path && (
                            <span title="fast-path resolution">
                              <Zap className="h-3.5 w-3.5 text-amber-400" />
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-ink-500">{inc.service}</div>
                      </td>
                      <td className="px-4 py-3">
                        <LevelBadge level={inc.escalation_level} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink-400">
                        {money(inc.cost_usd)}
                      </td>
                      <td className="px-4 py-3 text-right text-ink-500">{timeAgo(inc.created_at)}</td>
                      <td className="pr-3 text-ink-600">
                        <ChevronRight className="h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
