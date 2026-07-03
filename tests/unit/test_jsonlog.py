import json
from pathlib import Path

import pytest

from demoworld.common.jsonlog import JsonLogger, log_line, read_jsonl

pytestmark = pytest.mark.unit


def test_log_line_shape() -> None:
    rec = log_line(
        "shopapi",
        "ERROR",
        "payment call failed",
        path="/checkout",
        status=502,
        err_type="ConnectError",
    )
    assert rec["service"] == "shopapi"
    assert rec["level"] == "ERROR"
    assert rec["msg"] == "payment call failed"
    assert rec["status"] == 502
    assert rec["err_type"] == "ConnectError"
    assert rec["ts"].endswith("Z")


def test_log_line_drops_none_fields() -> None:
    rec = log_line("shopapi", "INFO", "ok", status=None, latency_ms=12)
    assert "status" not in rec
    assert rec["latency_ms"] == 12


def test_writer_appends_valid_jsonl(tmp_path: Path) -> None:
    lg = JsonLogger(tmp_path, "shopapi")
    lg.write("INFO", "one", latency_ms=5)
    lg.write("ERROR", "two", status=500)
    lines = (tmp_path / "shopapi.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["msg"] == "one"
    assert json.loads(lines[1])["status"] == 500


def test_read_jsonl_skips_torn_lines(tmp_path: Path) -> None:
    p = tmp_path / "logs.jsonl"
    # third line is a torn/partial write; fourth is blank — both must be skipped
    p.write_text('{"a": 1}\n{"b": 2}\n{"c": 3\n\n{"d": 4}\n', encoding="utf-8")
    recs = read_jsonl(p)
    assert [next(iter(r.keys())) for r in recs] == ["a", "b", "d"]


def test_read_jsonl_missing_file(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_read_jsonl_limit_returns_most_recent(tmp_path: Path) -> None:
    p = tmp_path / "logs.jsonl"
    p.write_text("".join(f'{{"i": {i}}}\n' for i in range(10)), encoding="utf-8")
    recs = read_jsonl(p, limit=3)
    assert [r["i"] for r in recs] == [7, 8, 9]


def test_rotation_creates_backup(tmp_path: Path) -> None:
    lg = JsonLogger(tmp_path, "shopapi", rotate_bytes=50)
    for i in range(20):
        lg.write("INFO", f"msg-{i}")
    assert (tmp_path / "shopapi.jsonl").exists()
    assert (tmp_path / "shopapi.jsonl.1").exists()  # rotated once past the tiny threshold
