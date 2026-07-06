"""Graph dependencies, injected into every node by ``build.py``. Keeping the router, tool
executor, policy, recovery timings, and the memory hooks here (rather than as globals) lets
tests wire a FakeLLM-backed router, a mocked actuator, near-instant recovery polling, and
stubbed memory recall/write."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from argus.llm.router import LLMRouter
from argus.memory.recall import recall as _recall
from argus.memory.writer import write_postmortem as _write_postmortem
from argus.policy.risk_gate import load_policy
from argus.tools.registry import ToolExecutor

# recall(alert) -> (memory_hits, fast_path_hint | None); list[Any] to stay assignable
# from recall's list[MemoryHit] return (lists are invariant)
RecallFn = Callable[[dict[str, Any]], tuple[list[Any], dict[str, Any] | None]]
# write_postmortem(state, router, *, incident_id, trace_id, parent_span_id) -> memory_id | None
WriteFn = Callable[..., str | None]


@dataclass
class GraphDeps:
    router: LLMRouter
    executor: ToolExecutor
    policy: dict[str, Any]
    # recovery polling — overridable so graph tests don't wait real seconds
    recovery_interval_s: float = 10.0
    recovery_deadline_s: float = 120.0
    recovery_sleep: Callable[[float], None] = field(default=time.sleep)
    # memory hooks (M07) — overridable so host graph tests never touch the embedder/DB
    recall: RecallFn = field(default=_recall)
    write_postmortem: WriteFn = field(default=_write_postmortem)


def default_deps() -> GraphDeps:
    """Production wiring: real router + tool executor + on-disk policy + real memory."""
    return GraphDeps(router=LLMRouter(), executor=ToolExecutor(), policy=load_policy())
