import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ApprovalCard, { type Decision } from "../components/ApprovalCard";
import { humanize } from "../components/StatusChip";
import { EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useApprovals } from "../queries";

export default function Approvals() {
  const pending = useApprovals("PENDING");
  const notify = useApprovals("AUTO");
  const all = useApprovals();
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  const decide = useMutation({
    mutationFn: ({ id, d }: { id: string; d: Decision }) => api.decideApproval(id, d),
    onSuccess: (res) => {
      setFlash({ kind: "ok", text: `Decision recorded — ${res.status.toLowerCase()}` });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
    },
    onError: (e: unknown) =>
      setFlash({ kind: "err", text: e instanceof Error ? e.message : "Decision failed" }),
  });

  const pendingList = pending.data ?? [];
  const notifyList = notify.data ?? [];
  const decided = (all.data ?? []).filter(
    (a) => !["PENDING", "AUTO"].includes(a.status),
  );

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Remediations Argus won't run without you"
        right={
          pendingList.length > 0 ? (
            <span className="rounded-full bg-amber-400 px-2.5 py-0.5 text-sm font-semibold text-amber-950">
              {pendingList.length} pending
            </span>
          ) : undefined
        }
      />
      <div className="max-w-3xl space-y-6 p-6">
        {flash && (
          <div
            className={`rounded-md border p-3 text-sm ${
              flash.kind === "ok"
                ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                : "border-rose-300 bg-rose-50 text-rose-700"
            }`}
          >
            {flash.text}
          </div>
        )}
        {pending.error && <ErrorNote error={pending.error} />}
        {pending.isLoading && !pending.data && <Spinner label="Loading approvals…" />}

        {pending.data && pendingList.length === 0 && (
          <EmptyState
            icon={<ShieldCheck className="h-8 w-8" />}
            title="Nothing to approve"
            hint="Argus resolves what it safely can on its own. When an action needs a human, it lands here — and the sidebar badge lights up."
          />
        )}
        {pendingList.map((a) => (
          <ApprovalCard
            key={a.id}
            approval={a}
            busy={decide.isPending}
            onDecide={(d) => decide.mutate({ id: a.id, d })}
          />
        ))}

        {notifyList.length > 0 && (
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-ink-500">
              <Bell className="h-3.5 w-3.5" /> Auto-remediated — for your awareness
            </div>
            <div className="card divide-y divide-ink-800">
              {notifyList.map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-3 p-3 text-sm">
                  <div className="min-w-0">
                    <Link to={`/incidents/${a.incident_id}`} className="text-ink-300 hover:text-accent">
                      {(a.proposed_action as any)?.tool} on {(a.proposed_action as any)?.target_service}
                    </Link>
                    <span className="ml-2 text-xs text-ink-500">{timeAgo(a.created_at)}</span>
                  </div>
                  <button
                    className="btn-ghost"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: a.id, d: { decision: "ack" } })}
                  >
                    Ack
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {decided.length > 0 && (
          <details>
            <summary className="cursor-pointer text-xs uppercase tracking-wide text-ink-500">
              Recently decided ({decided.length})
            </summary>
            <div className="card mt-2 divide-y divide-ink-800">
              {decided.slice(0, 15).map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-3 p-2.5 text-sm">
                  <Link to={`/incidents/${a.incident_id}`} className="truncate text-ink-400 hover:text-accent">
                    {(a.proposed_action as any)?.tool ?? a.level}
                  </Link>
                  <span className="text-xs text-ink-500">
                    {humanize(a.status)} · {timeAgo(a.decided_at)}
                  </span>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
