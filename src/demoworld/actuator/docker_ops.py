"""Container restarts for the actuator. Targets containers by their compose labels
(project + service) rather than name, since names vary with the project (08 #4)."""

from __future__ import annotations

from typing import Any

import docker


def restart_service(service: str, project: str = "argus", timeout: int = 10) -> dict[str, Any]:
    client = docker.from_env()  # type: ignore[attr-defined]  # dynamic; not in docker stubs
    try:
        containers = client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={project}",
                    f"com.docker.compose.service={service}",
                ]
            },
        )
        if not containers:
            return {"ok": False, "error": f"no container for service '{service}'"}
        restarted = []
        for container in containers:
            container.restart(timeout=timeout)
            restarted.append(container.name)
        return {"ok": True, "restarted": restarted}
    finally:
        client.close()
