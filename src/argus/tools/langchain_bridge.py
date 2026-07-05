"""Expose registry tools as LangChain StructuredTools, bound per agent (04 §5). Used by
the specialist tool-loops in M05; each tool wraps ToolExecutor.run so permission checks
and logging still apply. The LLM sees a JSON string result (errors included)."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from argus.tools.registry import ToolContext, ToolExecutor, ToolSpec


def tool_names_for_agent(agent: str, registry: dict[str, ToolSpec]) -> set[str]:
    return {name for name, spec in registry.items() if agent in spec.allowed_agents}


def _make_tool(
    agent: str, name: str, spec: ToolSpec, executor: ToolExecutor, context: ToolContext
) -> StructuredTool:
    def _call(**kwargs: object) -> str:
        return json.dumps(executor.run(agent, name, dict(kwargs), context=context), default=str)

    return StructuredTool.from_function(
        func=_call, name=name, description=spec.description, args_schema=spec.args_schema
    )


def tools_for_agent(
    agent: str, executor: ToolExecutor, context: ToolContext
) -> list[StructuredTool]:
    return [
        _make_tool(agent, name, spec, executor, context)
        for name, spec in executor.registry.items()
        if agent in spec.allowed_agents
    ]
