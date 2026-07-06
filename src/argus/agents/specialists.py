"""Specialist agent (04 §4; roles ``log_analyst``/``metrics_analyst``/``change_analyst``).

A ReAct-ish tool loop over the agent's permitted tools (native tool calling), capped at
``MAX_TOOL_CALLS`` per step, then a forced structured ``Finding``. Tool errors come back
from the executor as structured strings so the model can self-correct within its budget.

The final Finding call uses a *clean* message list (system + a plain-text observations
summary), not the raw tool-call/ToolMessage transcript — some providers reject tool
messages when the follow-up request binds no tools, and the excerpts belong in the
Finding anyway (08 #21). Any unrecoverable failure still yields a Finding: a failed step
is evidence too (confidence 0.0), which synthesize plans around (04 §1 edge table)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import structlog
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import StructuredTool

from argus.agents import prompts
from argus.agents.schemas import Finding, PlanStep
from argus.llm.router import LLMRouter
from argus.tools.langchain_bridge import tools_for_agent
from argus.tools.registry import ToolContext, ToolExecutor

log = structlog.get_logger(__name__)

MAX_TOOL_CALLS = 4  # per step (6 after M08)


def _invoke_tool(tools_by_name: dict[str, StructuredTool], call: Mapping[str, Any]) -> str:
    """Execute one tool call, returning the JSON result string (errors included so the
    model can self-correct rather than crash the loop — 08 #13)."""
    name = str(call.get("name", ""))
    tool = tools_by_name.get(name)
    if tool is None:
        return json.dumps({"ok": False, "error": f"tool '{name}' is not available to you"})
    try:
        return str(tool.invoke(call.get("args", {})))
    except Exception as exc:  # bad args / tool failure -> feed the error back to the model
        log.info("specialist.tool_error", tool=name, error=str(exc))
        return json.dumps({"ok": False, "error": f"{name} failed: {exc}"})


def run_step(
    router: LLMRouter,
    executor: ToolExecutor,
    specialist: str,
    alert: dict[str, Any],
    step: PlanStep,
    dependency_context: str = "",
    *,
    incident_id: str,
    trace_id: str,
    parent_span_id: str,
) -> tuple[Finding, int]:
    """Run one plan step. Returns (finding, llm_calls_made) so the node can bill budget."""
    context = ToolContext(
        node=specialist,
        incident_id=incident_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )
    tools = tools_for_agent(specialist, executor, context)
    tools_by_name = {t.name: t for t in tools}
    base = list(prompts.specialist_messages(specialist, alert, step.objective, dependency_context))
    loop_convo: list[BaseMessage] = list(base)
    observations: list[str] = []

    llm_calls = 0
    tool_calls_made = 0
    try:
        while tool_calls_made < MAX_TOOL_CALLS:
            ai = router.with_tools(
                specialist,
                loop_convo,
                tools,
                incident_id=incident_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
            )
            llm_calls += 1
            calls = list(ai.tool_calls or [])
            if not calls:
                if ai.content:
                    observations.append(str(ai.content))
                break
            loop_convo.append(ai)
            for call in calls:
                if tool_calls_made >= MAX_TOOL_CALLS:
                    break
                tool_calls_made += 1
                result = _invoke_tool(tools_by_name, call)
                observations.append(f"{call.get('name')}({dict(call.get('args', {}))}) -> {result}")
                loop_convo.append(ToolMessage(content=result, tool_call_id=str(call.get("id", ""))))

        summary = "\n".join(observations) or "No tool observations were gathered."
        finish_convo = [
            *base,
            prompts.specialist_observations_message(summary),
            prompts.specialist_finish_message(specialist, step.id),
        ]
        finding = router.structured(
            specialist,
            finish_convo,
            Finding,
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        llm_calls += 1
        # step_id / specialist are graph-owned facts, not the model's to choose
        return finding.model_copy(update={"step_id": step.id, "specialist": specialist}), llm_calls
    except Exception as exc:  # a failed step is evidence too (04 §1): confidence 0.0 finding
        log.warning("specialist.step_failed", specialist=specialist, step=step.id, error=str(exc))
        failed = Finding(
            step_id=step.id,
            specialist=specialist,
            summary=f"investigation step failed: {exc}",
            evidence=[],
            confidence=0.0,
        )
        return failed, llm_calls
