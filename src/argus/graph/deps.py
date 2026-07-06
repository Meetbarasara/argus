"""Graph dependencies, injected into every node by ``build.py``. Keeping the router,
tool executor, policy, and recovery timings here (rather than as globals) lets tests wire
a FakeLLM-backed router, a mocked actuator, and near-instant recovery polling."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from argus.llm.router import LLMRouter
from argus.policy.risk_gate import load_policy
from argus.tools.registry import ToolExecutor


@dataclass
class GraphDeps:
    router: LLMRouter
    executor: ToolExecutor
    policy: dict[str, Any]
    # recovery polling — overridable so graph tests don't wait real seconds
    recovery_interval_s: float = 10.0
    recovery_deadline_s: float = 120.0
    recovery_sleep: Callable[[float], None] = field(default=time.sleep)


def default_deps() -> GraphDeps:
    """Production wiring: real router + tool executor + on-disk policy."""
    return GraphDeps(router=LLMRouter(), executor=ToolExecutor(), policy=load_policy())
