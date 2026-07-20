import { Check, Pencil, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Approval, ProposedAction } from "../api";
import { timeAgo } from "../lib/format";
import { LevelBadge } from "./StatusChip";
import { ConfidenceBar, JsonBlock } from "./ui";

export interface Decision {
  decision: string;
  comment?: string;
  modified_action?: Record<string, any>;
}

export default function ApprovalCard({
  approval,
  onDecide,
  busy,
}: {
  approval: Approval;
  onDecide: (d: Decision) => void;
  busy?: boolean;
}) {
  const [mode, setMode] = useState<"view" | "modify" | "reject">("view");
  const action = approval.proposed_action as ProposedAction;
  const [params, setParams] = useState(() => JSON.stringify(action?.params ?? {}, null, 2));
  const [comment, setComment] = useState("");
  const [jsonErr, setJsonErr] = useState<string | null>(null);

  const ctx = approval.context ?? { evidence_excerpts: [], memory_refs: [], hypothesis: null, plan_summary: "" };
  const hyp = ctx.hypothesis ?? {};
  const evidence = ctx.evidence_excerpts ?? [];
  const memoryRefs = ctx.memory_refs ?? [];

  const submitModify = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(params);
    } catch {
      setJsonErr("Not valid JSON");
      return;
    }
    onDecide({ decision: "modify", modified_action: { ...action, params: parsed } });
  };

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <LevelBadge level={approval.level} />
          <Link
            to={`/incidents/${approval.incident_id}`}
            className="text-sm text-accent hover:underline"
          >
            view trace →
          </Link>
        </div>
        <span className="text-xs text-ink-500">{timeAgo(approval.created_at)}</span>
      </div>

      <div>
        <div className="text-xs uppercase tracking-wide text-ink-500">Root cause</div>
        <div className="mt-1 text-ink-100">{hyp.root_cause ?? "—"}</div>
        <div className="mt-2">
          <ConfidenceBar value={hyp.confidence} />
        </div>
      </div>

      <div className="rounded-md border border-ink-800 bg-ink-850/60 p-3">
        <div className="mb-1.5 text-xs uppercase tracking-wide text-ink-500">Proposed remediation</div>
        <div className="font-mono text-sm text-emerald-700">
          {action?.tool}(<span className="text-ink-300">{action?.target_service}</span>)
        </div>
        {action?.rationale && <div className="mt-1 text-sm text-ink-400">{action.rationale}</div>}
        <div className="mt-2">
          <JsonBlock data={action?.params ?? {}} />
        </div>
      </div>

      {evidence.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs uppercase tracking-wide text-ink-500">
            Evidence ({evidence.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {evidence.map((e, i) => (
              <li key={i} className="text-sm">
                <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[11px] text-ink-400">
                  {e.kind}
                </span>{" "}
                <span className="text-ink-500">{e.ref}</span>
                <div className="text-ink-300">{e.excerpt}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
      {memoryRefs.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-violet-700">
          <RefreshCw className="h-3 w-3" /> {memoryRefs.length} similar past incident(s) informed this
        </div>
      )}

      {/* TAKE_OVER rows resume as kind=takeover — the worker reads root_cause/action_taken,
          not an approve/reject verdict, so those buttons would silently drop the human's
          write-up. Point to the incident page, where the resolution form lives. */}
      {mode === "view" && approval.level === "TAKE_OVER" && (
        <div className="rounded-md border border-violet-300 bg-violet-50 p-3 text-sm text-violet-800">
          Argus handed this incident to you — approve/reject doesn’t apply here.{" "}
          <Link to={`/incidents/${approval.incident_id}`} className="font-medium underline">
            Record your resolution on the incident page →
          </Link>
        </div>
      )}
      {mode === "view" && approval.level !== "TAKE_OVER" && (
        <div className="flex flex-wrap gap-2 pt-1">
          <button
            disabled={busy}
            className="btn bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40"
            onClick={() => onDecide({ decision: "approve" })}
          >
            <Check className="h-4 w-4" /> Approve
          </button>
          <button disabled={busy} className="btn-ghost" onClick={() => setMode("modify")}>
            <Pencil className="h-4 w-4" /> Modify
          </button>
          <button disabled={busy} className="btn-danger" onClick={() => setMode("reject")}>
            <X className="h-4 w-4" /> Reject
          </button>
        </div>
      )}

      {mode === "modify" && (
        <div className="space-y-2">
          <div className="text-xs text-ink-500">
            Edit the action params — the server re-validates against the tool schema and re-runs
            the risk gate (a change that raises risk is rejected).
          </div>
          <textarea
            value={params}
            onChange={(e) => {
              setParams(e.target.value);
              setJsonErr(null);
            }}
            rows={5}
            spellCheck={false}
            className="w-full rounded-md border border-ink-700 bg-ink-900 p-2 font-mono text-xs text-ink-200 focus:border-accent focus:outline-none"
          />
          {jsonErr && <div className="text-xs text-rose-600">{jsonErr}</div>}
          <div className="flex gap-2">
            <button disabled={busy} className="btn-primary" onClick={submitModify}>
              Submit modified
            </button>
            <button className="btn-ghost" onClick={() => setMode("view")}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {mode === "reject" && (
        <div className="space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Why reject? (required — becomes reviewer feedback on the replan)"
            className="w-full rounded-md border border-ink-700 bg-ink-900 p-2 text-sm text-ink-200 focus:border-accent focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              disabled={busy || !comment.trim()}
              className="btn-danger"
              onClick={() => onDecide({ decision: "reject", comment })}
            >
              Confirm reject
            </button>
            <button className="btn-ghost" onClick={() => setMode("view")}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
