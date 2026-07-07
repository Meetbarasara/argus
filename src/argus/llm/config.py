"""Role → model resolution from config/models.yaml + ARGUS_MODEL__<ROLE> overrides (03 §3).
Model ids live only here / in config — never hardcoded in agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from argus.settings import model_overrides

MODELS_YAML = "config/models.yaml"


@dataclass(frozen=True)
class RoleModel:
    role: str
    provider: str
    model: str
    rpm: int
    env_key: str


def load_providers(path: str = MODELS_YAML) -> dict[str, dict]:
    """The ``providers`` block of models.yaml ({name: {env_key, rpm}}) — used to resolve the
    opt-in fallback model's api key + rate limit."""
    return dict(yaml.safe_load(Path(path).read_text(encoding="utf-8"))["providers"])


def load_model_config(path: str = MODELS_YAML) -> dict[str, RoleModel]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    providers = data["providers"]
    overrides = model_overrides()

    resolved: dict[str, RoleModel] = {}
    for role, cfg in data["roles"].items():
        provider = cfg["provider"]
        model = cfg["model"]
        if role in overrides:  # "provider:model"
            ov_provider, _, ov_model = overrides[role].partition(":")
            provider = ov_provider or provider
            model = ov_model or model
        prov = providers[provider]
        resolved[role] = RoleModel(role, provider, model, int(prov["rpm"]), prov["env_key"])
    return resolved
