import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Brain, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useMemories } from "../queries";

const KINDS: (string | undefined)[] = [undefined, "incident_pattern", "lesson"];

export default function Memory() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<string | undefined>(undefined);
  const { data, isLoading, error } = useMemories(term, kind);
  const qc = useQueryClient();
  const [flash, setFlash] = useState<string | null>(null);

  const del = useMutation({
    mutationFn: (id: string) => api.deleteMemory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  });
  const consolidate = useMutation({
    mutationFn: () => api.consolidate(),
    onSuccess: (r) => {
      setFlash(`Consolidated — ${r.merged} merged, ${r.decayed} decayed`);
      qc.invalidateQueries({ queryKey: ["memories"] });
    },
  });

  return (
    <div>
      <PageHeader
        title="Memory"
        subtitle="What Argus has learned from past incidents"
        right={
          <button className="btn-ghost" disabled={consolidate.isPending} onClick={() => consolidate.mutate()}>
            Consolidate
          </button>
        }
      />
      <div className="space-y-4 p-6">
        {flash && (
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
            {flash}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setTerm(q);
            }}
            className="relative min-w-[240px] flex-1"
          >
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-ink-600" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Semantic search… (e.g. redis down)"
              className="w-full rounded-md border border-ink-700 bg-ink-900 py-2 pl-9 pr-3 text-sm text-ink-200 focus:border-accent focus:outline-none"
            />
          </form>
          <div className="flex gap-1">
            {KINDS.map((k) => (
              <button
                key={k ?? "all"}
                onClick={() => setKind(k)}
                className={kind === k ? "btn-primary" : "btn-ghost"}
              >
                {k ? k.replace("_", " ") : "All"}
              </button>
            ))}
          </div>
        </div>

        {error && <ErrorNote error={error} />}
        {isLoading && !data && <Spinner label="Loading memories…" />}
        {data && data.length === 0 && (
          <EmptyState
            icon={<Brain className="h-8 w-8" />}
            title={term ? "No matches" : "No memories yet"}
            hint="Resolved incidents write a lesson here; the next similar incident recalls it — cutting the work."
          />
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data?.map((m) => (
            <div key={m.id} className="card space-y-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="font-medium text-ink-100">{m.title}</div>
                <button
                  className="text-ink-600 hover:text-rose-400"
                  title="delete memory"
                  onClick={() => window.confirm("Delete this memory?") && del.mutate(m.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="text-sm text-ink-400">{m.content}</div>
              <div className="flex flex-wrap gap-2 text-xs text-ink-500">
                <span className="rounded bg-ink-800 px-1.5 py-0.5">{m.kind}</span>
                <span>importance {m.importance.toFixed(2)}</span>
                <span>used {m.use_count}×</span>
                {m.last_used_at && <span>last {timeAgo(m.last_used_at)}</span>}
                {m.similarity != null && <span className="text-accent">sim {m.similarity.toFixed(2)}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
