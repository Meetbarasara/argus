"""Argus exception hierarchy (05). Nodes catch only what they can handle; everything
else bubbles to the task wrapper which marks the incident FAILED."""

from __future__ import annotations


class ArgusError(Exception):
    """Base for all Argus errors."""


class ToolError(ArgusError):
    """A tool failed unexpectedly (bad args / empty results are data, not this)."""


class LLMError(ArgusError):
    """Base for LLM-layer failures."""


class LLMRateLimitError(LLMError):
    """Provider rate limit exhausted after backoff."""


class LLMValidationError(LLMError):
    """Structured output failed schema validation after retries."""


class LLMReplayMissError(LLMError):
    """Replay mode had no cached response for the request."""


class PolicyError(ArgusError):
    """Invalid state transition or policy violation."""


class WorldError(ArgusError):
    """Demo-world interaction failed."""
