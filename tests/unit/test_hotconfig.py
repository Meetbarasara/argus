import json
from pathlib import Path
from typing import Any

import pytest

from demoworld.common.hotconfig import HotConfig

pytestmark = pytest.mark.unit


def _write(p: Path, cfg: dict[str, Any]) -> None:
    p.write_text(json.dumps(cfg), encoding="utf-8")


def test_loads_initial(tmp_path: Path) -> None:
    p = tmp_path / "shopapi.json"
    _write(p, {"version": "d-0001", "db_pool_size": 10})
    hc = HotConfig(p)
    assert hc.version == "d-0001"
    assert hc.get("db_pool_size") == 10


def test_reload_detects_version_change(tmp_path: Path) -> None:
    p = tmp_path / "shopapi.json"
    _write(p, {"version": "d-0001", "db_pool_size": 10})
    hc = HotConfig(p)
    _write(p, {"version": "d-0002", "db_pool_size": 2})
    assert hc.reload() is True
    assert hc.version == "d-0002"
    assert hc.get("db_pool_size") == 2
    assert hc.reload() is False  # no further change → no reload signal


def test_missing_file_keeps_last_known(tmp_path: Path) -> None:
    p = tmp_path / "shopapi.json"
    _write(p, {"version": "d-0001"})
    hc = HotConfig(p)
    p.unlink()
    assert hc.reload() is False
    assert hc.version == "d-0001"


def test_malformed_file_keeps_last_known(tmp_path: Path) -> None:
    p = tmp_path / "shopapi.json"
    _write(p, {"version": "d-0001"})
    hc = HotConfig(p)
    p.write_text("{ not valid json", encoding="utf-8")
    assert hc.reload() is False
    assert hc.version == "d-0001"
