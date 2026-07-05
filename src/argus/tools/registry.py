"""Tool registry + executor (04 §5, ADR-03/04).

The executor is the enforcement point: it validates args, checks ``allowed_agents``,
refuses mutating tools outside the remediate node, truncates results, and logs every
invocation (tool_calls row + tool span). Expected failures (bad args, permission,
not-found) come back as structured error dicts so an LLM tool-loop can self-correct;
only unexpected tool exceptions raise ToolError.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from argus.db.models import ToolCall
from argus.db.session import session_scope
from argus.errors import ToolError
from argus.obs.spans import span
from argus.tools import change_tools, remediation_tools, telemetry_tools
from argus.tools.schemas import (
    DeployDiffArgs,
    ListDeploysArgs,
    LogErrorSummaryArgs,
    QueryMetricsArgs,
    RecentActionsArgs,
    RestartServiceArgs,
    RollbackDeployArgs,
    SearchLogsArgs,
    ServiceHealthArgs,
)

MAX_ITEMS = 50
MAX_BYTES = 8192
REMEDIATE_NODE = "remediate"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    allowed_agents: frozenset[str]
    risk: str  # "read" | "mutating"
    func: Callable[[Any], Any]


@dataclass
class ToolContext:
    node: str = ""
    incident_id: str | None = None
    trace_id: str | None = None
    parent_span_id: str | None = None


@dataclass
class _Outcome:
    result_dict: dict[str, Any]
    status: str
    error: str | None
    exc: Exception | None = None


def _err(message: str) -> _Outcome:
    return _Outcome({"ok": False, "error": message}, "ERROR", message)


def _truncate(raw: Any) -> tuple[Any, bool]:
    truncated = False
    if isinstance(raw, list) and len(raw) > MAX_ITEMS:
        raw, truncated = raw[:MAX_ITEMS], True
    if len(json.dumps(raw, default=str).encode()) > MAX_BYTES:
        if isinstance(raw, list):
            while raw and len(json.dumps(raw, default=str).encode()) > MAX_BYTES:
                raw, truncated = raw[:-1], True
        else:
            truncated = True
    return raw, truncated


def build_registry() -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            "search_logs",
            "Search service logs (newest first).",
            SearchLogsArgs,
            frozenset({"log_analyst"}),
            "read",
            telemetry_tools.search_logs,
        ),
        ToolSpec(
            "log_error_summary",
            "Top normalized error templates + counts.",
            LogErrorSummaryArgs,
            frozenset({"log_analyst"}),
            "read",
            telemetry_tools.log_error_summary,
        ),
        ToolSpec(
            "query_metrics",
            "Query a metric series/aggregate for a service.",
            QueryMetricsArgs,
            frozenset({"metrics_analyst"}),
            "read",
            telemetry_tools.query_metrics,
        ),
        ToolSpec(
            "service_health",
            "Latest health snapshot per service (deps, pools).",
            ServiceHealthArgs,
            frozenset({"metrics_analyst"}),
            "read",
            telemetry_tools.service_health,
        ),
        ToolSpec(
            "list_deploys",
            "Recent deploy history entries.",
            ListDeploysArgs,
            frozenset({"change_analyst"}),
            "read",
            change_tools.list_deploys,
        ),
        ToolSpec(
            "deploy_diff",
            "Changes + before/after config for a deploy.",
            DeployDiffArgs,
            frozenset({"change_analyst"}),
            "read",
            change_tools.deploy_diff,
        ),
        ToolSpec(
            "recent_actions",
            "Recent actuator actions (restarts/chaos).",
            RecentActionsArgs,
            frozenset({"change_analyst"}),
            "read",
            change_tools.recent_actions,
        ),
        ToolSpec(
            "restart_service",
            "Restart a service container.",
            RestartServiceArgs,
            frozenset({REMEDIATE_NODE}),
            "mutating",
            remediation_tools.restart_service,
        ),
        ToolSpec(
            "rollback_deploy",
            "Roll back a deploy.",
            RollbackDeployArgs,
            frozenset({REMEDIATE_NODE}),
            "mutating",
            remediation_tools.rollback_deploy,
        ),
    ]
    return {s.name: s for s in specs}


class ToolExecutor:
    def __init__(self, registry: dict[str, ToolSpec] | None = None) -> None:
        self.registry = registry or build_registry()

    def run(
        self, agent: str, tool: str, args: dict[str, Any], *, context: ToolContext
    ) -> dict[str, Any]:
        start = time.monotonic()
        with span(
            f"tool.{tool}",
            "tool",
            incident_id=context.incident_id,
            trace_id=context.trace_id,
            parent_span_id=context.parent_span_id,
            attrs={"agent": agent, "tool": tool, "node": context.node},
        ) as sp:
            outcome = self._dispatch(agent, tool, args, context)
            sp.set(status=outcome.status)
            _write_tool_call(
                agent=agent,
                tool=tool,
                args=args,
                result=outcome.result_dict,
                status=outcome.status,
                error=outcome.error,
                latency_ms=int((time.monotonic() - start) * 1000),
                incident_id=context.incident_id,
                span_id=sp.span_id,
            )
        if outcome.exc is not None:
            raise outcome.exc
        return outcome.result_dict

    def _dispatch(
        self, agent: str, tool: str, args: dict[str, Any], context: ToolContext
    ) -> _Outcome:
        spec = self.registry.get(tool)
        if spec is None:
            return _err(f"unknown tool: {tool}")
        if agent not in spec.allowed_agents:
            return _err(f"agent '{agent}' is not allowed to use '{tool}'")
        if spec.risk == "mutating" and context.node != REMEDIATE_NODE:
            return _err(f"'{tool}' is mutating and only callable from the remediate node")
        try:
            validated = spec.args_schema.model_validate(args)
        except ValidationError as exc:
            return _err(f"invalid args for {tool}: {exc}")
        try:
            raw = spec.func(validated)
        except Exception as exc:  # unexpected tool failure → surface as ToolError
            return _Outcome(
                {"ok": False, "error": f"{tool} failed: {exc}"},
                "ERROR",
                str(exc),
                exc=ToolError(f"{tool} failed: {exc}"),
            )
        result, truncated = _truncate(raw)
        return _Outcome({"ok": True, "result": result, "truncated": truncated}, "OK", None)


def _write_tool_call(
    *,
    agent: str,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
    status: str,
    error: str | None,
    latency_ms: int,
    incident_id: str | None,
    span_id: str | None,
) -> None:
    with session_scope() as session:
        session.add(
            ToolCall(
                agent=agent,
                tool=tool,
                args=args,
                result=result,
                status=status,
                error=error,
                latency_ms=latency_ms,
                incident_id=incident_id,
                span_id=span_id,
            )
        )
