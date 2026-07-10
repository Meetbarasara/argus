// Typed thin fetch client — response types mirror 03 §4 verbatim (05). Base path /api,
// proxied to api:8080 by nginx (prod) or vite (dev).

export interface IncidentSummary {
  id: string;
  service: string;
  status: string;
  severity: string;
  title: string;
  created_at: string;
  updated_at: string;
  escalation_level: string | null;
  memory_used: boolean;
  fast_path: boolean;
  llm_calls: number;
  cost_usd: number;
}

export interface IncidentDetail extends IncidentSummary {
  trace_id: string | null;
  alert: Record<string, any>;
  alert_events: any[];
  root_cause: string | null;
  confidence: number | null;
  remediation: Record<string, any> | null;
  status_reason: string | null;
  resolved_at: string | null;
  mttr_seconds: number | null;
  tokens_in: number;
  tokens_out: number;
  tool_calls_count: number;
  approvals: Approval[];
}

export interface Span {
  span_id: string;
  trace_id: string;
  incident_id: string | null;
  parent_span_id: string | null;
  name: string;
  kind: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  attrs: Record<string, any>;
}

export interface LlmCall {
  id: string;
  incident_id: string | null;
  span_id: string | null;
  role: string;
  provider: string;
  model: string;
  messages: { role: string; content: string }[];
  response: Record<string, any>;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  validation_retries: number;
  mode: string;
  created_at: string;
}

export interface ToolCall {
  id: string;
  incident_id: string | null;
  span_id: string | null;
  agent: string;
  tool: string;
  args: Record<string, any>;
  result: Record<string, any>;
  status: string;
  error: string | null;
  latency_ms: number;
  created_at: string;
}

export interface ProposedAction {
  tool: string;
  params: Record<string, any>;
  target_service: string;
  rationale: string;
}

export interface ApprovalContext {
  hypothesis: { root_cause?: string; confidence?: number; affected_services?: string[] } | null;
  evidence_excerpts: { kind: string; ref: string; excerpt: string }[];
  plan_summary: string;
  memory_refs: string[];
}

export interface Approval {
  id: string;
  incident_id: string;
  created_at: string | null;
  decided_at: string | null;
  level: string;
  status: string;
  proposed_action: ProposedAction | Record<string, any>;
  context: ApprovalContext;
  decided_by: string | null;
  decision_comment: string | null;
  modified_action: Record<string, any> | null;
}

export interface Memory {
  id: string;
  kind: string;
  title: string;
  content: string;
  fingerprint: string;
  importance: number;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
  source_incident_id: string | null;
  superseded_by: string | null;
  similarity?: number;
}

export interface RoleCost {
  role: string;
  model: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface IncidentCost {
  incident_id: string;
  service: string;
  status: string;
  cost_usd: number;
  llm_calls: number;
}

export interface DashboardSummary {
  total_incidents: number;
  incidents_by_status: Record<string, number>;
  resolution_rate: number;
  escalation_rate: number;
  memory_used_share: number;
  avg_mttr_s: number | null;
  median_mttr_s: number | null;
  steps_to_diagnosis_avg: number | null;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  cost_by_role: RoleCost[];
  cost_per_incident: IncidentCost[];
}

export interface EvalRunConfig {
  memory_enabled?: boolean;
  supervisor_model?: string;
  llm_mode?: string;
  auto_approve?: string;
  ablation?: string;
  condition?: string;
}

export interface EvalRunSummary {
  id: string;
  suite: string;
  started_at: string | null;
  finished_at: string | null;
  config: EvalRunConfig;
  git_sha: string | null;
  notes: string | null;
  cases: number;
  passes: number;
}

export interface Health {
  status: string;
  db: boolean;
  redis: boolean;
  worldstate_mounted: boolean;
  config: {
    llm_mode: string;
    auto_approve: string;
    memory_enabled: boolean;
    supervisor_model: string;
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json" },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-json error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listIncidents: (status?: string) =>
    req<IncidentSummary[]>(`/incidents${status ? `?status=${status}` : ""}`),
  getIncident: (id: string) => req<IncidentDetail>(`/incidents/${id}`),
  getSpans: (id: string) => req<Span[]>(`/incidents/${id}/spans`),
  getLlmCall: (spanOrId: string) => req<LlmCall>(`/llm_calls/${spanOrId}`),
  getToolCall: (spanOrId: string) => req<ToolCall>(`/tool_calls/${spanOrId}`),
  listApprovals: (status?: string) =>
    req<Approval[]>(`/approvals${status ? `?status=${status}` : ""}`),
  decideApproval: (
    id: string,
    body: { decision: string; comment?: string; modified_action?: Record<string, any> },
  ) => req<{ status: string }>(`/approvals/${id}/decision`, { method: "POST", body: JSON.stringify(body) }),
  takeoverResolution: (id: string, body: { root_cause: string; action_taken: string }) =>
    req<{ status: string }>(`/incidents/${id}/takeover_resolution`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listMemories: (query?: string, kind?: string) => {
    const q = new URLSearchParams();
    if (query) q.set("query", query);
    if (kind) q.set("kind", kind);
    const qs = q.toString();
    return req<Memory[]>(`/memories${qs ? `?${qs}` : ""}`);
  },
  deleteMemory: (id: string) => req<{ deleted: string }>(`/memories/${id}`, { method: "DELETE" }),
  consolidate: () => req<{ merged: number; decayed: number }>(`/memories/consolidate`, { method: "POST" }),
  dashboard: () => req<DashboardSummary>(`/dashboard/summary`),
  evalRuns: () => req<EvalRunSummary[]>(`/evals/runs`),
  health: () => req<Health>(`/health`),
};
