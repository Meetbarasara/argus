"""Exhaustive risk-gate unit table (M05). Covers every scenario's expected base level,
the confidence overrides, strictness ordering (stricter override never weakens a level),
and the conservative TAKE_OVER fallbacks. Pure function — no DB, no LLM."""

import pytest

from argus.policy.risk_gate import LEVEL_ORDER, RiskDecision, evaluate_risk, load_policy, stricter

pytestmark = pytest.mark.unit

POLICY = load_policy()


def _level(tool: str, target: str, confidence: float) -> str:
    return evaluate_risk(
        tool=tool, target_service=target, confidence=confidence, policy=POLICY
    ).level


# --- scenario base levels (high confidence, no override) -----------------------------
@pytest.mark.parametrize(
    ("tool", "target", "expected"),
    [
        ("restart_service", "shopredis", "NOTIFY"),  # S1: cache
        ("restart_service", "paymentsvc", "APPROVE_ACTION"),  # S2: service
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S3: bad deploy
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S4: pool deploy
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S5: flag deploy
        ("restart_service", "shopapi", "APPROVE_ACTION"),  # service class
        ("restart_service", "shopdb", "APPROVE_PLAN"),  # database class
    ],
)
def test_scenario_base_levels(tool: str, target: str, expected: str) -> None:
    assert _level(tool, target, 0.9) == expected


# --- confidence overrides ------------------------------------------------------------
def test_confidence_below_060_bumps_to_at_least_approve_action() -> None:
    # cache restart is NOTIFY at high confidence; 0.5 < 0.60 bumps it to APPROVE_ACTION
    assert _level("restart_service", "shopredis", 0.9) == "NOTIFY"
    assert _level("restart_service", "shopredis", 0.5) == "APPROVE_ACTION"


def test_confidence_below_035_forces_take_over() -> None:
    assert _level("restart_service", "shopredis", 0.34) == "TAKE_OVER"
    assert _level("rollback_deploy", "shopapi", 0.2) == "TAKE_OVER"


def test_override_boundaries_are_strict() -> None:
    # exactly at a threshold is NOT below it
    assert _level("restart_service", "shopredis", 0.60) == "NOTIFY"
    assert _level("restart_service", "shopredis", 0.35) == "APPROVE_ACTION"  # <0.60 only


def test_stricter_override_never_weakens_a_higher_base() -> None:
    # database restart is APPROVE_PLAN; the 0.5 "at_least APPROVE_ACTION" must NOT weaken it
    assert _level("restart_service", "shopdb", 0.5) == "APPROVE_PLAN"
    # but 0.3 still forces TAKE_OVER (stricter than APPROVE_PLAN)
    assert _level("restart_service", "shopdb", 0.3) == "TAKE_OVER"


# --- conservative fallbacks ----------------------------------------------------------
def test_unknown_service_takes_over() -> None:
    assert _level("restart_service", "mystery-svc", 0.99) == "TAKE_OVER"


def test_unknown_action_takes_over() -> None:
    assert _level("scale_up", "shopapi", 0.99) == "TAKE_OVER"


# --- trace + helpers -----------------------------------------------------------------
def test_rule_trace_is_populated() -> None:
    decision = evaluate_risk(
        tool="restart_service", target_service="shopredis", confidence=0.3, policy=POLICY
    )
    assert isinstance(decision, RiskDecision)
    assert decision.level == "TAKE_OVER"
    # trace records base rule + both overrides that fired
    assert any("restart_service on shopredis" in line for line in decision.rule_trace)
    assert any("0.35" in line for line in decision.rule_trace)


def test_stricter_helper() -> None:
    assert stricter("AUTO", "NOTIFY") == "NOTIFY"
    assert stricter("APPROVE_PLAN", "APPROVE_ACTION") == "APPROVE_PLAN"
    assert stricter("TAKE_OVER", "AUTO") == "TAKE_OVER"
    assert LEVEL_ORDER.index("AUTO") < LEVEL_ORDER.index("TAKE_OVER")
