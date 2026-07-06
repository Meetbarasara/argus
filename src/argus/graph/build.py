"""Compile the incident-response graph (04 §1 topology).

Specialist execution has two shapes behind ``deps.parallel_specialists`` (04 §1: "M05 runs
D1–D3 sequentially; M08 switches to parallel fan-out with the Send API and a joining
reducer"):

* parallel (default) — ``plan`` dispatches one ``Send`` per ready step; the specialist nodes
  append findings concurrently and converge on the ``gather`` join, which dispatches a second
  wave for any dependent steps before flowing to ``synthesize`` (08 #20: interrupts stay
  strictly *after* the join, never inside the fan-out);
* sequential — the M05 chain, kept for the A/B latency demo, converging on the same join.

Two cross-cutting concerns stay here so the nodes remain thin:
  * every single (non-fanned-out) LLM node gets a pre-node budget guard — on breach it
    short-circuits and the following conditional edge routes to take_over (04 edge table);
  * all conditional routing (fan-out waves, review verdict, risk level, recovery outcome)
    lives in the pure router functions below, keyed off state the nodes already wrote. In the
    parallel path the budget/degradation checks happen once before the fan-out (after plan)
    and once after the join (gather), never per parallel branch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from argus.graph import fanout
from argus.graph.deps import GraphDeps
from argus.graph.nodes import (
    close,
    gather,
    human_approval,
    intake,
    plan,
    postmortem,
    recall,
    remediate,
    review,
    risk_gate,
    specialists,
    synthesize,
    take_over,
)
from argus.graph.state import IncidentState
from argus.graph.support import budget_breach_reason, mark_breached
from argus.graph.verify import verify_recovery

NodeFn = Callable[[dict[str, Any], GraphDeps], dict[str, Any]]
Runnable = Callable[[dict[str, Any]], dict[str, Any]]

SPECIALISTS = ("log_analyst", "metrics_analyst", "change_analyst")


def _plain(fn: NodeFn, deps: GraphDeps) -> Runnable:
    def run(state: dict[str, Any]) -> dict[str, Any]:
        return fn(state, deps)

    return run


def _guarded(fn: NodeFn, deps: GraphDeps) -> Runnable:
    """Wrap an LLM node with the pre-node budget guard (04 edge table)."""

    def run(state: dict[str, Any]) -> dict[str, Any]:
        reason = budget_breach_reason(state, deps.policy)
        if reason is not None:
            return {"budget": mark_breached(state), "status_reason": reason}
        return fn(state, deps)

    return run


# --- conditional routers -------------------------------------------------------------
def _breached(state: dict[str, Any]) -> bool:
    return bool((state.get("budget") or {}).get("breached"))


def _route_budget(next_node: str) -> Callable[[dict[str, Any]], str]:
    def route(state: dict[str, Any]) -> str:
        return "take_over" if _breached(state) else next_node

    return route


def _fan_out(state: dict[str, Any]) -> list[Send]:
    """One Send per ready step; the specialist reads its step from ``current_step``."""
    return [
        Send(step.specialist, {**state, "current_step": step})
        for step in fanout.remaining_steps(state)
    ]


def _route_after_plan(state: dict[str, Any]) -> Any:
    """plan → fan out the first wave (steps with no unmet depends_on), or take_over on breach."""
    if _breached(state):  # plan's guard short-circuited, or plan's own call tipped the budget
        return "take_over"
    sends = _fan_out(state)
    # plan schema guarantees ≥1 step and a plan with a root, so a wave is always non-empty;
    # fall through to synthesize defensively rather than emit an empty Send list.
    return sends or "synthesize"


def _route_after_gather(state: dict[str, Any]) -> Any:
    """Join → next dependent wave, else take_over (breach/degraded), else synthesize."""
    if _breached(state):
        return "take_over"
    sends = _fan_out(state)
    if sends:
        return sends
    if fanout.investigation_degraded(state):
        return "take_over"
    return "synthesize"


def _route_review(deps: GraphDeps) -> Callable[[dict[str, Any]], str]:
    max_loops = int(deps.policy["limits"]["max_review_loops"])

    def route(state: dict[str, Any]) -> str:
        if _breached(state):
            return "take_over"
        history = state.get("review_history", [])
        if not history:
            return "take_over"
        if history[-1].verdict == "approve":
            return "risk_gate"
        # revise/reject: loop back to synthesize while under the loop budget, else escalate
        if len(history) >= max_loops:
            return "take_over"
        return "synthesize"

    return route


def _route_approval(state: dict[str, Any]) -> str:
    decision = (state.get("approval_decision") or {}).get("decision")
    return "remediate" if decision in ("approve", "modify") else "plan"


def _route_gate(state: dict[str, Any]) -> str:
    level = (state.get("escalation") or {}).get("level", "TAKE_OVER")
    if level in ("AUTO", "NOTIFY"):
        return "remediate"
    if level in ("APPROVE_ACTION", "APPROVE_PLAN"):
        return "human_approval"
    return "take_over"


def _route_verify(deps: GraphDeps) -> Callable[[dict[str, Any]], str]:
    max_attempts = int(deps.policy["limits"]["max_remediation_attempts"])

    def route(state: dict[str, Any]) -> str:
        if (state.get("recovery") or {}).get("recovered"):
            return "postmortem"
        if len(state.get("remediation_attempts", [])) >= max_attempts:
            return "take_over"
        return "plan"

    return route


def build_graph(deps: GraphDeps, checkpointer: Any) -> Any:
    # typed as Any: LangGraph's add_node/add_conditional_edges overloads reject plain
    # (state) -> dict callables; the wiring below is simple and covered by graph tests.
    graph: Any = StateGraph(IncidentState)

    graph.add_node("intake", _plain(intake.intake, deps))
    graph.add_node("recall_memory", _plain(recall.recall_memory, deps))
    graph.add_node("plan", _guarded(plan.plan, deps))
    graph.add_node("gather", _plain(gather.gather, deps))
    graph.add_node("synthesize", _guarded(synthesize.synthesize, deps))
    graph.add_node("review", _guarded(review.review, deps))
    graph.add_node("risk_gate", _plain(risk_gate.risk_gate, deps))
    graph.add_node("human_approval", _plain(human_approval.human_approval, deps))
    graph.add_node("remediate", _plain(remediate.remediate, deps))
    graph.add_node("verify_recovery", _plain(verify_recovery, deps))
    graph.add_node("postmortem", _plain(postmortem.postmortem, deps))
    graph.add_node("take_over", _plain(take_over.take_over, deps))
    graph.add_node("close", _plain(close.close, deps))

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "recall_memory")
    graph.add_edge("recall_memory", "plan")

    # the fan-out join is shared by both modes; a Send target list covers the dynamic edges
    gather_ends = ["take_over", "synthesize", *SPECIALISTS]
    if deps.parallel_specialists:
        for name in SPECIALISTS:
            graph.add_node(name, _plain(getattr(specialists, name), deps))
            graph.add_edge(name, "gather")
        graph.add_conditional_edges("plan", _route_after_plan, gather_ends)
        graph.add_conditional_edges("gather", _route_after_gather, gather_ends)
    else:
        # sequential chain (PARALLEL_SPECIALISTS=false): each specialist runs all its steps,
        # fronted by the budget guard's routing, converging on the same gather join.
        for name in SPECIALISTS:
            graph.add_node(name, _guarded(getattr(specialists, name), deps))
        graph.add_conditional_edges(
            "plan", _route_budget("log_analyst"), ["take_over", "log_analyst"]
        )
        graph.add_conditional_edges(
            "log_analyst", _route_budget("metrics_analyst"), ["take_over", "metrics_analyst"]
        )
        graph.add_conditional_edges(
            "metrics_analyst", _route_budget("change_analyst"), ["take_over", "change_analyst"]
        )
        graph.add_conditional_edges(
            "change_analyst", _route_budget("gather"), ["take_over", "gather"]
        )
        graph.add_conditional_edges("gather", _route_after_gather, gather_ends)

    graph.add_conditional_edges("synthesize", _route_budget("review"), ["take_over", "review"])
    graph.add_conditional_edges(
        "review", _route_review(deps), ["take_over", "synthesize", "risk_gate"]
    )
    graph.add_conditional_edges(
        "risk_gate", _route_gate, ["remediate", "human_approval", "take_over"]
    )
    graph.add_edge("remediate", "verify_recovery")
    graph.add_conditional_edges(
        "verify_recovery", _route_verify(deps), ["postmortem", "plan", "take_over"]
    )
    graph.add_edge("postmortem", "close")
    graph.add_edge("close", END)

    # M06 HITL: both nodes interrupt() and resume from their checkpoint. human_approval
    # resumes to remediate (approve/modify) or plan (reject); take_over resumes to
    # postmortem once a human posts a takeover resolution.
    graph.add_conditional_edges("human_approval", _route_approval, ["remediate", "plan"])
    graph.add_edge("take_over", "postmortem")

    return graph.compile(checkpointer=checkpointer)
