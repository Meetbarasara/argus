import json
from pathlib import Path

import pytest

from demoworld.actuator.deploys import DeployManager, get_by_path, set_by_path

pytestmark = pytest.mark.unit


def _seed_config(ws: Path, service: str, cfg: dict) -> None:
    p = ws / "config" / f"{service}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg), encoding="utf-8")


def test_path_helpers():
    d = {"feature_flags": {"recs_v2": False}, "db_pool_size": 10}
    assert get_by_path(d, "db_pool_size") == 10
    assert get_by_path(d, "feature_flags.recs_v2") is False
    assert get_by_path(d, "missing.key") is None
    set_by_path(d, "feature_flags.recs_v2", True)
    assert d["feature_flags"]["recs_v2"] is True
    set_by_path(d, "new.nested.key", 5)
    assert d["new"]["nested"]["key"] == 5


def test_deploy_records_change_and_bumps_version(tmp_path: Path):
    _seed_config(
        tmp_path, "shopapi", {"version": "d-0000", "payment_url": "http://paymentsvc:8000"}
    )
    dm = DeployManager(tmp_path)
    entry = dm.deploy(
        "shopapi", {"payment_url": "http://paymentsvc:9999"}, "break payments", "injector"
    )
    assert entry["deploy_id"] == "d-0001"
    assert entry["changes"]["payment_url"] == {
        "old": "http://paymentsvc:8000",
        "new": "http://paymentsvc:9999",
    }
    live = json.loads((tmp_path / "config" / "shopapi.json").read_text())
    assert live["payment_url"] == "http://paymentsvc:9999"
    assert live["version"] == "d-0001"
    assert (tmp_path / entry["snapshot_before"]).exists()
    assert (tmp_path / entry["snapshot_after"]).exists()


def test_deploy_ids_are_monotonic(tmp_path: Path):
    _seed_config(tmp_path, "shopapi", {"version": "d-0000", "db_pool_size": 10})
    dm = DeployManager(tmp_path)
    assert dm.deploy("shopapi", {"db_pool_size": 5}, "m", "injector")["deploy_id"] == "d-0001"
    assert dm.deploy("shopapi", {"db_pool_size": 2}, "m", "injector")["deploy_id"] == "d-0002"
    assert dm.next_deploy_id() == "d-0003"


def test_nested_flag_deploy(tmp_path: Path):
    _seed_config(tmp_path, "shopapi", {"version": "d-0000", "feature_flags": {"recs_v2": False}})
    dm = DeployManager(tmp_path)
    dm.deploy("shopapi", {"feature_flags.recs_v2": True}, "enable recs", "injector")
    live = json.loads((tmp_path / "config" / "shopapi.json").read_text())
    assert live["feature_flags"]["recs_v2"] is True


def test_rollback_restores_prior_config(tmp_path: Path):
    _seed_config(
        tmp_path, "shopapi", {"version": "d-0000", "payment_url": "http://paymentsvc:8000"}
    )
    dm = DeployManager(tmp_path)
    bad = dm.deploy("shopapi", {"payment_url": "http://paymentsvc:9999"}, "break", "injector")
    rb = dm.rollback(bad["deploy_id"], "human")
    live = json.loads((tmp_path / "config" / "shopapi.json").read_text())
    assert live["payment_url"] == "http://paymentsvc:8000"  # restored
    assert rb["deploy_id"] == "d-0002"
    assert rb["rollback_of"] == "d-0001"
    assert live["version"] == "d-0002"


def test_list_deploys_newest_first_and_filtered(tmp_path: Path):
    _seed_config(tmp_path, "shopapi", {"version": "d-0000", "db_pool_size": 10})
    _seed_config(tmp_path, "paymentsvc", {"version": "d-0000", "base_latency_ms": 40})
    dm = DeployManager(tmp_path)
    dm.deploy("shopapi", {"db_pool_size": 5}, "a", "injector")
    dm.deploy("paymentsvc", {"base_latency_ms": 50}, "b", "injector")
    dm.deploy("shopapi", {"db_pool_size": 2}, "c", "injector")
    shop = dm.list_deploys(service="shopapi")
    assert [e["deploy_id"] for e in shop] == ["d-0003", "d-0001"]
    assert len(dm.list_deploys()) == 3
