"""Container restarts for the actuator. Targets containers by their compose labels
(project + service) rather than name, since names vary with the project (08 #4)."""

from __future__ import annotations

from typing import Any

import docker


def _containers_for(client: Any, service: str, project: str) -> list[Any]:
    return client.containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={project}",
                f"com.docker.compose.service={service}",
            ]
        },
    )


def restart_service(service: str, project: str = "argus", timeout: int = 10) -> dict[str, Any]:
    client = docker.from_env()  # type: ignore[attr-defined]  # dynamic; not in docker stubs
    try:
        containers = _containers_for(client, service, project)
        if not containers:
            return {"ok": False, "error": f"no container for service '{service}'"}
        restarted = [c.name for c in containers]
        for container in containers:
            container.restart(timeout=timeout)
        return {"ok": True, "restarted": restarted}
    finally:
        client.close()


def stop_service(service: str, project: str = "argus", timeout: int = 5) -> dict[str, Any]:
    """Stop a service's container(s) — used only for fault injection (S1)."""
    client = docker.from_env()  # type: ignore[attr-defined]  # dynamic; not in docker stubs
    try:
        containers = _containers_for(client, service, project)
        if not containers:
            return {"ok": False, "error": f"no container for service '{service}'"}
        stopped = [c.name for c in containers]
        for container in containers:
            container.stop(timeout=timeout)
        return {"ok": True, "stopped": stopped}
    finally:
        client.close()
