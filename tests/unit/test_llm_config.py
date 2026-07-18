import pytest

from argus.llm.config import load_model_config

pytestmark = pytest.mark.unit


def test_default_roles_resolve():
    cfg = load_model_config()
    # High-volume roles route off Gemini (daily-cap exhaustion fix, 2026-07-19); the judge
    # stays on Gemini as the one low-volume exception.
    assert cfg["supervisor"].provider == "cerebras"
    assert cfg["supervisor"].rpm == 25
    assert cfg["supervisor"].env_key == "CEREBRAS_API_KEY"
    assert cfg["log_analyst"].provider == "groq"
    assert cfg["judge"].provider == "gemini"


def test_env_override_role_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGUS_MODEL__SUPERVISOR", "groq:llama-3.3-70b-versatile")
    cfg = load_model_config()
    assert cfg["supervisor"].provider == "groq"
    assert cfg["supervisor"].model == "llama-3.3-70b-versatile"
    assert cfg["supervisor"].env_key == "GROQ_API_KEY"
