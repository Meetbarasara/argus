"""Compile the incident-response graph (04 §1 topology). M05 wires the specialists as a
sequential chain (M08 swaps in the Send-API fan-out); everything else matches the diagram.

Two cross-cutting concerns are handled here so the nodes stay thin:
  * every LLM node gets a pre-node budget guard — on breach it short-circuits and the
    following conditional edge routes to take_over (04 edge table);
  * all conditional routing (review verdict, risk level, recovery outcome) lives in the
    pure router functions below, keyed off state the nodes already wrote.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from argus.graph.deps import GraphDeps
from argus.graph.nodes import (
    close,
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
def _route_budget(next_node: str) -> Callable[[dict[str, Any]], str]:
    def route(state: dict[str, Any]) -> str:
        return "take_over" if (state.get("budget") or {}).get("breached") else next_node

    return route


def _route_review(deps: GraphDeps) -> Callable[[dict[str, Any]], str]:
    max_loops = int(deps.policy["limits"]["max_review_loops"])

    def route(state: dict[str, Any]) -> str:
        if (state.get("budget") or {}).get("breached"):
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
    graph.add_node("log_analyst", _guarded(specialists.log_analyst, deps))
    graph.add_node("metrics_analyst", _guarded(specialists.metrics_analyst, deps))
    graph.add_node("change_analyst", _guarded(specialists.change_analyst, deps))
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

    # sequential specialist chain, each fronted by the budget guard's routing
    graph.add_conditional_edges("plan", _route_budget("log_analyst"), ["take_over", "log_analyst"])
    graph.add_conditional_edges(
        "log_analyst", _route_budget("metrics_analyst"), ["take_over", "metrics_analyst"]
    )
    graph.add_conditional_edges(
        "metrics_analyst", _route_budget("change_analyst"), ["take_over", "change_analyst"]
    )
    graph.add_conditional_edges(
        "change_analyst", _route_budget("synthesize"), ["take_over", "synthesize"]
    )
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

    # M05 holds: no interrupt yet — these terminal-park the incident and end the run.
    graph.add_edge("human_approval", END)
    graph.add_edge("take_over", END)

    return graph.compile(checkpointer=checkpointer)
