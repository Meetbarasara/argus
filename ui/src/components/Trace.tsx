import { useQuery } from "@tanstack/react-query";
import { Box, ChevronDown, ChevronRight, Globe, Scale, Sparkles, User, Wrench } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { api, type Span } from "../api";
import { duration, money } from "../lib/format";
import { buildSpanTree, countDescendants, flattenTree, type SpanNode } from "../lib/spanTree";
import { SPAN_KIND_COLOR } from "../lib/status";
import { JsonBlock } from "./ui";

const KIND_ICON = {
  node: Box,
  llm: Sparkles,
  tool: Wrench,
  policy: Scale,
  human: User,
  world: Globe,
} as const;

export default function Trace({ spans }: { spans: Span[] }) {
  const roots = useMemo(() => buildSpanTree(spans), [spans]);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const rows = useMemo(() => flattenTree(roots, collapsed), [roots, collapsed]);
  const selected = spans.find((s) => s.span_id === selectedId) ?? null;

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_420px]">
      <div className="card overflow-hidden">
        {rows.map((node: SpanNode) => {
          const { span, depth, children } = node;
          const Icon = KIND_ICON[span.kind as keyof typeof KIND_ICON] ?? Box;
          const hasChildren = children.length > 0;
          const isOpen = !collapsed.has(span.span_id);
          return (
            <button
              key={span.span_id}
              onClick={() => setSelectedId(span.span_id)}
              className={`flex w-full items-center gap-2 border-b border-ink-800/50 px-2 py-1.5 text-left text-sm hover:bg-ink-800/40 ${
                selectedId === span.span_id ? "bg-accent/10" : ""
              }`}
            >
              <span style={{ paddingLeft: depth * 16 }} className="flex items-center">
                {hasChildren ? (
                  <span
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(span.span_id);
                    }}
                    className="text-ink-600 hover:text-ink-300"
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </span>
                ) : (
                  <span className="inline-block w-3.5" />
                )}
              </span>
              <Icon className={`h-3.5 w-3.5 shrink-0 ${SPAN_KIND_COLOR[span.kind] ?? "text-ink-400"}`} />
              <span className="truncate text-ink-200">{span.name}</span>
              {hasChildren && !isOpen && (
                <span className="text-[10px] text-ink-600">+{countDescendants(node)}</span>
              )}
              <span className="ml-auto flex items-center gap-2 pl-2 text-xs text-ink-500">
                <span className="tabular-nums">{duration(span.duration_ms)}</span>
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    span.status === "ERROR" ? "bg-rose-500" : "bg-emerald-500/60"
                  }`}
                />
              </span>
            </button>
          );
        })}
      </div>

      <div className="lg:sticky lg:top-4 lg:self-start">
        {selected ? (
          <SpanDetail span={selected} />
        ) : (
          <div className="card p-6 text-sm text-ink-500">
            Select a span to inspect its attributes, prompt, or tool I/O.
          </div>
        )}
      </div>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-ink-400">{children}</span>;
}

function SpanDetail({ span }: { span: Span }) {
  return (
    <div className="card space-y-3 p-4">
      <div>
        <div className="font-mono text-sm text-ink-100">{span.name}</div>
        <div className="mt-1 flex gap-3 text-xs text-ink-500">
          <span>{span.kind}</span>
          <span className={span.status === "ERROR" ? "text-rose-400" : "text-emerald-400"}>
            {span.status}
          </span>
          <span>{duration(span.duration_ms)}</span>
        </div>
      </div>
      {span.kind === "llm" && <LlmDetail spanId={span.span_id} />}
      {span.kind === "tool" && <ToolDetail spanId={span.span_id} />}
      {Object.keys(span.attrs ?? {}).length > 0 && (
        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-ink-500">Attributes</div>
          <JsonBlock data={span.attrs} />
        </div>
      )}
    </div>
  );
}

function LlmDetail({ spanId }: { spanId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["llm_call", spanId],
    queryFn: () => api.getLlmCall(spanId),
    retry: false,
  });
  if (isLoading) return <div className="text-xs text-ink-500">loading prompt…</div>;
  if (error || !data)
    return <div className="text-xs text-ink-600">No LLM call recorded for this span.</div>;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Tag>{data.role}</Tag>
        <Tag>{data.model}</Tag>
        <Tag>
          {data.tokens_in}→{data.tokens_out} tok
        </Tag>
        <Tag>{money(data.cost_usd)}</Tag>
        <Tag>{data.latency_ms}ms</Tag>
        <Tag>{data.mode}</Tag>
      </div>
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-ink-500">Prompt</div>
        <div className="max-h-64 space-y-1.5 overflow-auto rounded-md border border-ink-800 bg-ink-950 p-2">
          {data.messages.map((m, i) => (
            <div key={i} className="text-xs">
              <span className="text-ink-600">{m.role}: </span>
              <span className="whitespace-pre-wrap text-ink-300">{m.content}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-ink-500">Response</div>
        <JsonBlock data={data.response} />
      </div>
    </div>
  );
}

function ToolDetail({ spanId }: { spanId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["tool_call", spanId],
    queryFn: () => api.getToolCall(spanId),
    retry: false,
  });
  if (isLoading) return <div className="text-xs text-ink-500">loading tool I/O…</div>;
  if (error || !data)
    return <div className="text-xs text-ink-600">No tool call recorded for this span.</div>;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Tag>{data.agent}</Tag>
        <Tag>{data.tool}</Tag>
        <Tag>{data.latency_ms}ms</Tag>
      </div>
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-ink-500">Args</div>
        <JsonBlock data={data.args} />
      </div>
      <div>
        <div className="mb-1 text-xs uppercase tracking-wide text-ink-500">Result</div>
        <JsonBlock data={data.error ? { error: data.error } : data.result} />
      </div>
    </div>
  );
}
