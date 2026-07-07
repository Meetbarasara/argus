import { ArrowLeft, Brain, Zap } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { IncidentDetail as IncidentT, Span } from "../api";
import { StatusChip } from "../components/StatusChip";
import Trace from "../components/Trace";
import { ConfidenceBar, EmptyState, ErrorNote, JsonBlock, KeyVal, Spinner } from "../components/ui";
import { money, seconds, timeAgo } from "../lib/format";
import { useIncident, useSpans } from "../queries";

type Tab = "trace" | "hypothesis" | "remediation" | "memory";
const TABS: { id: Tab; label: string }[] = [
  { id: "trace", label: "Trace" },
  { id: "hypothesis", label: "Hypothesis & Review" },
  { id: "remediation", label: "Remediation" },
  { id: "memory", label: "Memory" },
];

const findByName = (spans: Span[], name: string) => spans.find((s) => s.name === name);

export default function IncidentDetail() {
  const { id = "" } = useParams();
  const [tab, setTab] = useState<Tab>("trace");
  const incident = useIncident(id);
  const spansQ = useSpans(id);
  const spans = spansQ.data ?? [];
  const inc = incident.data;

  return (
    <div>
      <div className="border-b border-ink-800 px-6 py-4">
        <Link to="/" className="mb-2 inline-flex items-center gap-1 text-xs text-ink-500 hover:text-ink-300">
          <ArrowLeft className="h-3.5 w-3.5" /> Incidents
        </Link>
        {incident.error && <ErrorNote error={incident.error} />}
        {inc && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-ink-100">{inc.title}</h1>
              <StatusChip status={inc.status} />
              {inc.memory_used && (
                <span title="memory recalled">
                  <Brain className="h-4 w-4 text-violet-400" />
                </span>
              )}
              {inc.fast_path && (
                <span title="fast-path">
                  <Zap className="h-4 w-4 text-amber-400" />
                </span>
              )}
            </div>
            {inc.status_reason && <p className="mt-1 text-sm text-ink-500">{inc.status_reason}</p>}
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-400">
              <span>service <span className="text-ink-200">{inc.service}</span></span>
              <span>opened <span className="text-ink-200">{timeAgo(inc.created_at)}</span></span>
              {inc.mttr_seconds != null && (
                <span>MTTR <span className="text-ink-200">{seconds(inc.mttr_seconds)}</span></span>
              )}
              <span>{inc.llm_calls} LLM · {inc.tool_calls_count} tool calls</span>
              <span>cost <span className="text-ink-200">{money(inc.cost_usd)}</span></span>
            </div>
          </>
        )}
      </div>

      <div className="flex gap-1 border-b border-ink-800 px-6">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2.5 text-sm transition-colors ${
              tab === t.id
                ? "border-accent text-ink-100"
                : "border-transparent text-ink-500 hover:text-ink-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="p-6">
        {spansQ.isLoading && !spansQ.data && <Spinner label="Loading trace…" />}
        {tab === "trace" &&
          (spans.length ? (
            <Trace spans={spans} />
          ) : (
            !spansQ.isLoading && <EmptyState title="No spans yet" hint="The investigation is just starting — this fills in live." />
          ))}
        {tab === "hypothesis" && inc && <HypothesisTab inc={inc} spans={spans} />}
        {tab === "remediation" && inc && <RemediationTab inc={inc} spans={spans} />}
        {tab === "memory" && inc && <MemoryTab inc={inc} spans={spans} />}
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card space-y-3 p-4">
      <div className="text-xs uppercase tracking-wide text-ink-500">{title}</div>
      {children}
    </div>
  );
}

function HypothesisTab({ inc, spans }: { inc: IncidentT; spans: Span[] }) {
  const specialists = spans.filter(
    (s) => s.kind === "node" && /log_analyst|metrics_analyst|change_analyst/.test(s.name),
  );
  const reviews = spans.filter((s) => s.name === "node.review");
  const plan = findByName(spans, "node.plan");
  const evidence = (inc.approvals ?? []).flatMap((a) => a?.context?.evidence_excerpts ?? []);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Root cause">
        <div className="text-ink-100">{inc.root_cause ?? "Still investigating…"}</div>
        {inc.confidence != null && <ConfidenceBar value={inc.confidence} />}
      </Card>

      <Card title={`Investigation${plan?.attrs?.steps ? ` · ${plan.attrs.steps} steps` : ""}`}>
        {specialists.length === 0 && <div className="text-sm text-ink-500">No specialist findings yet.</div>}
        <div className="space-y-1.5">
          {specialists.map((s) => (
            <div key={s.span_id} className="flex items-center justify-between text-sm">
              <span className="text-ink-300">{s.name.replace("node.", "")}</span>
              {s.attrs?.confidence != null ? (
                <ConfidenceBar value={s.attrs.confidence} />
              ) : (
                <span className="text-xs text-ink-600">{s.status}</span>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card title="Reviewer verdicts">
        {reviews.length === 0 && <div className="text-sm text-ink-500">Not yet reviewed.</div>}
        <ol className="space-y-1 text-sm">
          {reviews.map((s, i) => (
            <li key={s.span_id} className="flex gap-2">
              <span className="text-ink-600">#{i + 1}</span>
              <span
                className={
                  s.attrs?.verdict === "approve"
                    ? "text-emerald-300"
                    : s.attrs?.verdict === "reject"
                      ? "text-rose-300"
                      : "text-amber-300"
                }
              >
                {s.attrs?.verdict ?? "—"}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      <Card title={`Evidence (${evidence.length})`}>
        {evidence.length === 0 && <div className="text-sm text-ink-500">Open the Trace tab to see tool observations.</div>}
        <ul className="space-y-2">
          {evidence.slice(0, 8).map((e, i) => (
            <li key={i} className="text-sm">
              <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[11px] text-ink-400">{e.kind}</span>{" "}
              <span className="text-ink-500">{e.ref}</span>
              <div className="text-ink-300">{e.excerpt}</div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function RemediationTab({ inc, spans }: { inc: IncidentT; spans: Span[] }) {
  const verify = findByName(spans, "node.verify_recovery");
  const rem = inc.remediation;
  if (!rem)
    return <EmptyState title="No remediation" hint="This incident resolved without an action, is still investigating, or was handed to a human." />;
  const action = rem.action ?? rem;
  const result = rem.result;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Executed action">
        <div className="font-mono text-sm text-emerald-300">
          {action?.tool}(<span className="text-ink-300">{action?.target_service ?? action?.params?.service ?? ""}</span>)
        </div>
        {action?.params && <JsonBlock data={action.params} />}
      </Card>
      <Card title="Actuator result">
        {result ? <JsonBlock data={result} /> : <div className="text-sm text-ink-500">Pending…</div>}
      </Card>
      <Card title="Recovery verification">
        {verify ? (
          <div className="space-y-1 text-sm">
            <KeyVal k="recovered">
              <span className={verify.attrs?.recovered ? "text-emerald-300" : "text-rose-300"}>
                {String(verify.attrs?.recovered ?? "—")}
              </span>
            </KeyVal>
            <KeyVal k="checks">{verify.attrs?.checks ?? "—"}</KeyVal>
          </div>
        ) : (
          <div className="text-sm text-ink-500">Not verified yet.</div>
        )}
      </Card>
    </div>
  );
}

function MemoryTab({ inc, spans }: { inc: IncidentT; spans: Span[] }) {
  const postmortem = findByName(spans, "node.postmortem");
  const wrote = postmortem?.attrs?.memory_id;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Recall">
        <div className="flex gap-2 text-sm">
          <span className={inc.memory_used ? "text-violet-300" : "text-ink-500"}>
            {inc.memory_used ? "memory recalled" : "no memory used"}
          </span>
          {inc.fast_path && <span className="text-amber-300">· fast-path</span>}
        </div>
      </Card>
      <Card title="Written">
        {wrote ? (
          <div className="text-sm text-emerald-300">
            memory {String(wrote).slice(0, 8)} written from this incident
          </div>
        ) : (
          <div className="text-sm text-ink-500">No memory written (yet).</div>
        )}
      </Card>
    </div>
  );
}
