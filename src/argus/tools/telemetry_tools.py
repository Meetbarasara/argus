"""log_analyst + metrics_analyst read tools (04 §5). Pure reads over worldstate."""

from __future__ import annotations

from typing import Any

from argus.tools import worldstate
from argus.tools.schemas import (
    LogErrorSummaryArgs,
    QueryMetricsArgs,
    SearchLogsArgs,
    ServiceHealthArgs,
)


def search_logs(args: SearchLogsArgs) -> list[dict[str, Any]]:
    lines = worldstate.read_logs(args.service, args.since_minutes)
    if args.level:
        level = args.level.upper()
        lines = [ln for ln in lines if ln.get("level") == level]
    if args.contains:
        needle = args.contains.lower()
        lines = [ln for ln in lines if needle in str(ln.get("msg", "")).lower()]
    lines.sort(key=lambda ln: str(ln.get("ts", "")), reverse=True)
    return lines[: args.limit]


def log_error_summary(args: LogErrorSummaryArgs) -> list[dict[str, Any]]:
    return worldstate.error_templates(worldstate.read_logs(args.service, args.since_minutes))


def query_metrics(args: QueryMetricsArgs) -> dict[str, Any]:
    lines = worldstate.read_metrics(args.service, args.metric, args.since_minutes)
    values = [ln["value"] for ln in lines if isinstance(ln.get("value"), int | float)]
    base = {"metric": args.metric, "service": args.service, "agg": args.agg}
    if args.agg == "raw":
        return {**base, "series": lines[-50:]}
    if not values:
        return {**base, "value": None, "samples": 0}
    if args.agg == "last":
        value: float = values[-1]
    elif args.agg == "avg":
        value = round(sum(values) / len(values), 4)
    else:
        value = max(values)
    return {**base, "value": value, "samples": len(values)}


def service_health(args: ServiceHealthArgs) -> dict[str, Any]:  # noqa: ARG001 - no args
    return worldstate.latest_health()
