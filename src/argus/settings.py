"""All environment access lives here (05: no os.environ reads elsewhere)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM providers (03 §6)
    google_api_key: str = ""
    groq_api_key: str = ""
    llm_mode: Literal["live", "record", "replay", "fake"] = "live"

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
    dev_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
