"""Unit: the modify re-gate rule (M06 acceptance) — a human may narrow risk but never
widen it past the level policy allowed. Pure logic over the risk gate; no DB/network."""

import pytest
from fastapi import HTTPException

from argus.api.routers.approvals import _revalidate_and_regate
from argus.db.models import Approval

pytestmark = pytest.mark.unit


def _approval(level: str, confidence: float = 0.9) -> Approval:
    return Approval(level=level, context={"hypothesis": {"confidence": confidence}})


def _action(tool: str, target: str, params: dict) -> dict:
    return {"tool": tool, "params": params, "target_service": target, "rationale": "test"}


def test_modify_same_level_ok() -> None:
    # rollback_deploy re-gates to APPROVE_ACTION == approved level -> allowed
    _revalidate_and_regate(
        _approval("APPROVE_ACTION"),
        _action("rollback_deploy", "shopapi", {"deploy_id": "d-0001"}),
    )


def test_modify_lower_level_ok() -> None:
    # cache restart re-gates to NOTIFY (< APPROVE_ACTION) -> narrowing risk is allowed
    _revalidate_and_regate(
        _approval("APPROVE_ACTION"),
        _action("restart_service", "shopredis", {"service": "shopredis"}),
    )


def test_modify_raising_risk_is_rejected() -> None:
    # database restart re-gates to APPROVE_PLAN (> APPROVE_ACTION) -> 422
    with pytest.raises(HTTPException) as exc:
        _revalidate_and_regate(
            _approval("APPROVE_ACTION"),
            _action("restart_service", "shopdb", {"service": "shopdb"}),
        )
    assert exc.value.status_code == 422


def test_modify_bad_params_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _revalidate_and_regate(
            _approval("APPROVE_ACTION"),
            _action("rollback_deploy", "shopapi", {"wrong_arg": "x"}),
        )
    assert exc.value.status_code == 422


def test_modify_missing_action_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _revalidate_and_regate(_approval("APPROVE_ACTION"), None)
    assert exc.value.status_code == 422
