"""LLMRouter — the single hardened entry point for every LLM call (M03).

Orchestrates: role→model resolution, record/replay cache, per-provider rate limiting,
structured-output parsing with validation-retry, cost accounting, and llm_calls + span
logging. Agents (M05) only ever call ``structured`` or ``with_tools``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis
import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from argus.db.session import session_scope
from argus.errors import LLMReplayMissError, LLMValidationError
from argus.llm import costs, parsing, recorder
from argus.llm.config import RoleModel, load_model_config, load_providers
from argus.llm.fake import FakeLLM, load_fake_from_scripts
from argus.llm.logging import write_llm_call
from argus.llm.providers import build_chat_model
from argus.llm.ratelimit import acquire
from argus.obs.spans import span
from argus.settings import get_settings

log = structlog.get_logger(__name__)

MAX_VALIDATION_RETRIES = 2
_RATE_LIMIT_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "ratelimit",
    "quota",
    "too many requests",
)


def _is_rate_limited(exc: Exception) -> bool:
    """Heuristic across providers: Gemini raises RESOURCE_EXHAUSTED/429, Groq raises rate-limit
    errors — both surface these markers in the message."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


class _FallbackModel:
    """Wraps a primary chat model with an ordered chain of fallbacks. On a rate-limit / quota
    error it retries the next model in the chain, and so on — so exhausting one free tier rolls
    onto the next (each model, even another of the same provider, carries its own per-model
    daily budget). Non-rate-limit errors propagate unchanged; if every link is exhausted the
    last error is raised. Tokens/cost stay logged against the role's configured primary model."""

    def __init__(self, models: list[Any]) -> None:
        self._models = models  # [primary, fallback1, fallback2, …]

    def _wrap(self, model: Any, tools: Any) -> Any:
        return model.bind_tools(tools) if hasattr(model, "bind_tools") else model

    def bind_tools(self, tools: Any) -> _FallbackModel:
        return _FallbackModel([self._wrap(m, tools) for m in self._models])

    def invoke(self, messages: Any) -> Any:
        last: Exception | None = None
        for i, model in enumerate(self._models):
            try:
                return model.invoke(messages)
            except Exception as exc:
                if not _is_rate_limited(exc):
                    raise
                last = exc
                if i + 1 < len(self._models):
                    log.warning("llm.fallback", step=i + 1, error=str(exc)[:120])
        assert last is not None  # the loop only exits via return unless a rate-limit was seen
        raise last


def _to_dicts(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return [{"role": getattr(m, "type", "user"), "content": str(m.content)} for m in messages]


def _concat(messages: list[BaseMessage]) -> str:
    return "\n".join(str(m.content) for m in messages)


class LLMRouter:
    def __init__(self, *, mode: str | None = None, fake: FakeLLM | None = None) -> None:
        settings = get_settings()
        self.mode = mode or settings.llm_mode
        self.config = load_model_config()
        self.prices = costs.load_prices()
        self._redis = redis.Redis.from_url(settings.redis_url)
        self._models: dict[str, Any] = {}
        self._providers = load_providers()
        self._fb_models: dict[str, Any] = {}  # lazily-built fallback chat models, cached by id
        if fake is not None:
            self.fake: FakeLLM | None = fake
        elif self.mode == "fake":
            self.fake = load_fake_from_scripts()
        else:
            self.fake = None

    def _model_for(self, role: str) -> Any:
        if self.fake is not None:
            return self.fake.for_role(role)
        rm = self.config[role]
        if role not in self._models:
            api_key = get_settings().api_key_for(rm.env_key)
            self._models[role] = build_chat_model(rm.provider, rm.model, api_key)
        primary = self._models[role]
        chain = self._fallback_chain(rm)
        return _FallbackModel([primary, *chain]) if chain else primary

    def _fallback_chain(self, rm: RoleModel) -> list[Any]:
        """Build the ``LLM_FALLBACK`` chain: a comma-separated list of ``provider:model`` tried
        in order when the primary is rate-limited. A different *model* — even one of the same
        provider — has its own per-model free-tier budget, so same-provider fallbacks are kept;
        only the exact primary model is skipped. Unknown providers / malformed entries ignored."""
        chain: list[Any] = []
        for entry in get_settings().llm_fallback.split(","):
            provider, _, model = entry.strip().partition(":")
            if not provider or not model or (provider == rm.provider and model == rm.model):
                continue
            prov = self._providers.get(provider)
            if prov is None:
                continue
            key = f"{provider}:{model}"
            if key not in self._fb_models:
                self._fb_models[key] = build_chat_model(
                    provider, model, get_settings().api_key_for(prov["env_key"])
                )
            chain.append(self._fb_models[key])
        return chain

    def structured[T: BaseModel](
        self,
        role: str,
        messages: list[BaseMessage],
        schema: type[T],
        *,
        incident_id: str | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> T:
        rm = self.config[role]
        msg_dicts = _to_dicts(messages)
        key = recorder.cache_key(role, rm.model, msg_dicts, schema.__name__)

        if self.mode in ("replay", "record"):
            with session_scope() as session:
                cached = recorder.lookup_cached(session, key)
            if cached is not None:
                return schema.model_validate(cached["parsed"])
            if self.mode == "replay":
                raise LLMReplayMissError(f"replay miss: {role}/{schema.__name__}")

        with span(
            f"llm.{role}",
            "llm",
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attrs={"role": role, "provider": rm.provider, "model": rm.model, "mode": self.mode},
        ) as sp:
            if self.fake is None:
                acquire(self._redis, rm.provider, rm.rpm)
            result, raw, tokens_in, tokens_out, estimated, retries, latency_ms = (
                self._invoke_structured(role, messages, schema)
            )
            cost = costs.compute_cost(rm.provider, rm.model, tokens_in, tokens_out, self.prices)
            sp.set(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost),
                validation_retries=retries,
                estimated=estimated,
            )
            write_llm_call(
                role=role,
                provider=rm.provider,
                model=rm.model,
                messages=msg_dicts,
                response={"raw": raw, "parsed": result.model_dump(mode="json")},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                validation_retries=retries,
                mode=self.mode,
                cache_key=key,
                incident_id=incident_id,
                span_id=sp.span_id,
            )
        return result

    def _invoke_structured[T: BaseModel](
        self, role: str, messages: list[BaseMessage], schema: type[T]
    ) -> tuple[T, str, int, int, bool, int, int]:
        model = self._model_for(role)
        instruction = SystemMessage(
            content="Respond with ONLY a JSON object matching this schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        convo: list[BaseMessage] = [instruction, *messages]
        start = time.monotonic()
        last_err: Exception | None = None
        raw = ""
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            ai = model.invoke(convo)
            raw = ai.content if isinstance(ai.content, str) else str(ai.content)
            try:
                parsed = parsing.parse_structured(raw, schema)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = exc
                fix = f"That was invalid for the schema: {exc}. Return ONLY corrected JSON."
                convo = [*convo, AIMessage(content=raw), HumanMessage(content=fix)]
                continue
            latency_ms = int((time.monotonic() - start) * 1000)
            tokens_in, tokens_out, estimated = costs.extract_usage(ai, _concat(convo), raw)
            return parsed, raw, tokens_in, tokens_out, estimated, attempt, latency_ms
        raise LLMValidationError(f"{role} structured output invalid after retries: {last_err}")

    def with_tools(
        self,
        role: str,
        messages: list[BaseMessage],
        tools: list[Any],
        *,
        incident_id: str | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> AIMessage:
        rm = self.config[role]
        with span(
            f"llm.{role}",
            "llm",
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attrs={"role": role, "provider": rm.provider, "model": rm.model, "mode": self.mode},
        ) as sp:
            if self.fake is None:
                acquire(self._redis, rm.provider, rm.rpm)
            model = self._model_for(role)
            bound = model.bind_tools(tools) if hasattr(model, "bind_tools") else model
            start = time.monotonic()
            ai = bound.invoke(messages)
            latency_ms = int((time.monotonic() - start) * 1000)
            tokens_in, tokens_out, estimated = costs.extract_usage(
                ai, _concat(messages), str(ai.content)
            )
            cost = costs.compute_cost(rm.provider, rm.model, tokens_in, tokens_out, self.prices)
            sp.set(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost),
                estimated=estimated,
            )
            write_llm_call(
                role=role,
                provider=rm.provider,
                model=rm.model,
                messages=_to_dicts(messages),
                response={
                    "content": str(ai.content),
                    "tool_calls": getattr(ai, "tool_calls", []),
                },
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                validation_retries=0,
                mode=self.mode,
                cache_key=recorder.cache_key(role, rm.model, _to_dicts(messages), "with_tools"),
                incident_id=incident_id,
                span_id=sp.span_id,
            )
        return ai

    def resolve(self, role: str) -> RoleModel:
        return self.config[role]
