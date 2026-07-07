import { levelClasses, severityClasses, statusClasses } from "../lib/status";

export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function StatusChip({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded border px-2 py-0.5 text-xs font-medium ${statusClasses(status)}`}
    >
      {humanize(status)}
    </span>
  );
}

export function LevelBadge({ level }: { level: string | null | undefined }) {
  if (!level) return null;
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${levelClasses(level)}`}
    >
      {humanize(level)}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] uppercase tracking-wide ${severityClasses(severity)}`}
    >
      {severity}
    </span>
  );
}
