import pytest

from argus.settings import Settings

pytestmark = pytest.mark.unit


def test_defaults_load_without_env() -> None:
    s = Settings(_env_file=None)
    assert s.llm_mode == "live"
    assert s.auto_approve == "off"
    assert s.memory_enabled is True
    assert s.worldstate_path == "/worldstate"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    s = Settings(_env_file=None)
    assert s.llm_mode == "replay"
    assert s.memory_enabled is False
