// Visual mapping for the incident state machine (03 §1) — kept pure so it is unit-testable
// without React. Tones group the many statuses into a handful of meanings the eye can scan.

export type Tone = "active" | "waiting" | "success" | "danger" | "escalated" | "neutral";

const STATUS_TONE: Record<string, Tone> = {
  OPEN: "active",
  INVESTIGATING: "active",
  REMEDIATING: "active",
  RECOVERED: "success",
  WAITING_APPROVAL: "waiting",
  RESOLVED: "success",
  TAKEN_OVER: "escalated",
  FAILED: "danger",
  CLOSED: "neutral",
};

export const TONE_CLASSES: Record<Tone, string> = {
  active: "text-sky-300 bg-sky-500/10 border-sky-500/30",
  waiting: "text-amber-300 bg-amber-500/10 border-amber-500/40",
  success: "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
  danger: "text-rose-300 bg-rose-500/10 border-rose-500/30",
  escalated: "text-violet-300 bg-violet-500/10 border-violet-500/30",
  neutral: "text-ink-400 bg-ink-800 border-ink-700",
};

export function statusTone(status: string): Tone {
  return STATUS_TONE[status] ?? "neutral";
}

export function statusClasses(status: string): string {
  return TONE_CLASSES[statusTone(status)];
}

export function severityClasses(sev: string): string {
  if (sev === "critical") return "text-rose-300 border-rose-500/40";
  if (sev === "warning") return "text-amber-300 border-amber-500/40";
  return "text-ink-400 border-ink-700";
}

// escalation level → risk badge tone (approval cards): the stricter the level, the hotter
export const LEVEL_CLASSES: Record<string, string> = {
  AUTO: TONE_CLASSES.success,
  NOTIFY: TONE_CLASSES.active,
  APPROVE_ACTION: TONE_CLASSES.waiting,
  APPROVE_PLAN: TONE_CLASSES.waiting,
  TAKE_OVER: TONE_CLASSES.escalated,
};

export function levelClasses(level: string | null | undefined): string {
  return (level && LEVEL_CLASSES[level]) || TONE_CLASSES.neutral;
}

// span kind → accent color for the trace tree (icons live in the component)
export const SPAN_KIND_COLOR: Record<string, string> = {
  node: "text-ink-200",
  llm: "text-accent",
  tool: "text-emerald-400",
  policy: "text-amber-300",
  human: "text-violet-300",
  world: "text-ink-400",
};
