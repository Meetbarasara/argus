// Visual mapping for the incident state machine (03 §1) — kept pure so it is unit-testable
// without React. Tones group the many statuses into a handful of meanings the eye can scan.
// Light theme: deep-hue text (-700/-800) on a pale tint (-50/-100) keeps chips ≥ AA contrast.

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
  active: "text-sky-700 bg-sky-100/70 border-sky-300",
  waiting: "text-amber-800 bg-amber-100/80 border-amber-300",
  success: "text-emerald-700 bg-emerald-100/70 border-emerald-300",
  danger: "text-rose-700 bg-rose-100/70 border-rose-300",
  escalated: "text-violet-700 bg-violet-100/70 border-violet-300",
  neutral: "text-ink-400 bg-ink-850 border-ink-700",
};

export function statusTone(status: string): Tone {
  return STATUS_TONE[status] ?? "neutral";
}

export function statusClasses(status: string): string {
  return TONE_CLASSES[statusTone(status)];
}

export function severityClasses(sev: string): string {
  if (sev === "critical") return "text-rose-700 border-rose-300";
  if (sev === "warning") return "text-amber-700 border-amber-400";
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
  tool: "text-emerald-600",
  policy: "text-amber-600",
  human: "text-violet-600",
  world: "text-ink-400",
};
