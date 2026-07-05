import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argus.tools import change_tools, telemetry_tools, worldstate
from argus.tools.schemas import (
    DeployDiffArgs,
    ListDeploysArgs,
    LogErrorSummaryArgs,
    SearchLogsArgs,
)

pytestmark = pytest.mark.unit


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WORLDSTATE_PATH", str(tmp_path))
    return tmp_path


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_read_jsonl_skips_torn_lines(tmp_path: Path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\n{ torn\n\n{"b":2}\n', encoding="utf-8")
    assert [next(iter(r)) for r in worldstate.read_jsonl(p)] == ["a", "b"]


def test_normalize_template_groups_and_masks():
    a = worldstate.normalize_template("payment call failed: status 502")
    b = worldstate.normalize_template("payment call failed: status 500")
    assert a == b == "payment call failed: status <*>"
    assert worldstate.normalize_template('connect to "paymentsvc:9999"') == "connect to <*>"
    assert worldstate.normalize_template("pool timeout after 0.35s") == "pool timeout after <*>s"


def test_search_logs_filters_by_level_and_contains(ws: Path):
    _write(
        ws / "logs" / "shopapi.jsonl",
        [
            {
                "ts": _now(),
                "service": "shopapi",
                "level": "ERROR",
                "msg": "checkout ConnectError",
                "status": 502,
            },
            {"ts": _now(), "service": "shopapi", "level": "INFO", "msg": "served /products"},
        ],
    )
    errs = telemetry_tools.search_logs(SearchLogsArgs(service="shopapi", level="ERROR"))
    assert len(errs) == 1 and errs[0]["status"] == 502
    hits = telemetry_tools.search_logs(SearchLogsArgs(service="shopapi", contains="connecterror"))
    assert len(hits) == 1


def test_log_error_summary_ranks_top_template(ws: Path):
    _write(
        ws / "logs" / "shopapi.jsonl",
        [
            {
                "ts": _now(),
                "service": "shopapi",
                "level": "ERROR",
                "msg": "payment call failed: status 502",
            },
            {
                "ts": _now(),
                "service": "shopapi",
                "level": "ERROR",
                "msg": "payment call failed: status 500",
            },
            {"ts": _now(), "service": "shopapi", "level": "ERROR", "msg": "one-off error"},
        ],
    )
    summary = telemetry_tools.log_error_summary(LogErrorSummaryArgs(service="shopapi"))
    assert summary[0] == {"template": "payment call failed: status <*>", "count": 2}


def test_list_deploys_and_deploy_diff(ws: Path):
    entry = {
        "deploy_id": "d-0001",
        "ts": _now(),
        "service": "shopapi",
        "message": "repoint payments",
        "changes": {"payment_url": {"old": "a", "new": "b"}},
    }
    _write(ws / "deploys" / "history.jsonl", [entry])
    deploys = change_tools.list_deploys(ListDeploysArgs(service="shopapi"))
    assert deploys[0]["deploy_id"] == "d-0001"
    diff = change_tools.deploy_diff(DeployDiffArgs(deploy_id="d-0001"))
    assert diff["found"] is True and "payment_url" in diff["changes"]
    assert change_tools.deploy_diff(DeployDiffArgs(deploy_id="d-9999"))["found"] is False


def test_old_lines_filtered_out(ws: Path):
    _write(
        ws / "logs" / "shopapi.jsonl",
        [
            {
                "ts": "2020-01-01T00:00:00.000Z",
                "service": "shopapi",
                "level": "ERROR",
                "msg": "ancient",
            }
        ],
    )
    assert telemetry_tools.search_logs(SearchLogsArgs(service="shopapi", since_minutes=60)) == []
