"""change_analyst read tools (04 §5): deploy history, per-deploy diff, actuator audit.
Reads worldstate directly for uniformity; only mutations go through the actuator."""

from __future__ import annotations

from typing import Any

from argus.tools import worldstate
from argus.tools.schemas import DeployDiffArgs, ListDeploysArgs, RecentActionsArgs


def list_deploys(args: ListDeploysArgs) -> list[dict[str, Any]]:
    deploys = worldstate.read_deploys(args.since_minutes)
    if args.service:
        deploys = [d for d in deploys if d.get("service") == args.service]
    deploys.sort(key=lambda d: str(d.get("ts", "")), reverse=True)
    return deploys[: args.limit]


def deploy_diff(args: DeployDiffArgs) -> dict[str, Any]:
    entry = worldstate.find_deploy(args.deploy_id)
    if entry is None:
        return {"found": False, "deploy_id": args.deploy_id}
    return {
        "found": True,
        "deploy_id": args.deploy_id,
        "service": entry.get("service"),
        "message": entry.get("message"),
        "author": entry.get("author"),
        "changes": entry.get("changes"),
        "config_before": worldstate.read_snapshot_ref(entry.get("snapshot_before")),
        "config_after": worldstate.read_snapshot_ref(entry.get("snapshot_after")),
    }


def recent_actions(args: RecentActionsArgs) -> list[dict[str, Any]]:
    actions = worldstate.read_actions(args.since_minutes)
    actions.sort(key=lambda a: str(a.get("ts", "")), reverse=True)
    return actions
