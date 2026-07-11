"""All environment access lives here (05: no os.environ reads elsewhere)."""

import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_MODEL_OVERRIDE_PREFIX = "ARGUS_MODEL__"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM providers (03 §6)
    google_api_key: str = ""
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    llm_mode: Literal["live", "record", "replay", "fake"] = "live"
    # Opt-in fallback CHAIN: on a rate-limit/quota error the router retries the call down this
    # comma-separated list of ``provider:model`` fallbacks in order (each free model has its own
    # budget, so exhausting one rolls to the next). Empty = off (default; no behaviour change).
    llm_fallback: str = ""

    # Behavior toggles
    auto_approve: Literal["off", "policy_sim"] = "off"
    memory_enabled: bool = True
    parallel_specialists: bool = True

    # Infrastructure
    database_url: str = "postgresql+psycopg://argus:argus@localhost:5433/argus"
    redis_url: str = "redis://localhost:6380/0"
    platform_api_url: str = "http://localhost:8080"
    actuator_url: str = "http://localhost:8010"
    actuator_token: str = "dev-actuator-token"
    worldstate_path: str = "/worldstate"

    # Observability
    otel_export_jaeger: bool = False
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    git_sha: str = "dev"  # resource attr on spans (set at build/deploy)
    dev_mode: bool = False

    def api_key_for(self, env_key: str) -> str:
        return {
            "GOOGLE_API_KEY": self.google_api_key,
            "GROQ_API_KEY": self.groq_api_key,
            "CEREBRAS_API_KEY": self.cerebras_api_key,
        }.get(env_key, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def model_overrides() -> dict[str, str]:
    """Per-role model overrides from ``ARGUS_MODEL__<ROLE>=provider:model`` (03 §3).

    Dynamic per-role env keys can't be pydantic fields, so this is the one other place
    env is read — kept here so all env access still lives in settings.
    """
    return {
        key[len(_MODEL_OVERRIDE_PREFIX) :].lower(): value
        for key, value in os.environ.items()
        if key.startswith(_MODEL_OVERRIDE_PREFIX) and value
    }
