import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-ink-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-ink-800 p-12 text-center">
      {icon && <div className="text-ink-600">{icon}</div>}
      <div className="text-sm font-medium text-ink-300">{title}</div>
      {hint && <div className="max-w-sm text-xs text-ink-500">{hint}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
      Couldn’t reach the API: {msg}
    </div>
  );
}

export function ConfidenceBar({ value }: { value: number | null | undefined }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const hue = v >= 0.7 ? "bg-emerald-500" : v >= 0.4 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-ink-800">
        <div className={`h-full ${hue}`} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ink-400">{Math.round(v * 100)}%</span>
    </div>
  );
}

export function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="overflow-x-auto rounded-md border border-ink-800 bg-ink-850 p-3 font-mono text-xs leading-relaxed text-ink-200">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function KeyVal({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="w-32 shrink-0 text-ink-500">{k}</span>
      <span className="min-w-0 break-words text-ink-200">{children}</span>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4 border-b border-ink-800 px-6 py-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink-100">{title}</h1>
        {subtitle && <p className="mt-0.5 truncate text-sm text-ink-500">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
