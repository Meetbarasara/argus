"""M09 span attribute contract (03 §1 spans.attrs, 04 node table): every span kind carries
the attrs the UI + dashboard depend on. The fixtures mirror what each emit site sets
(llm.router, tool executor, risk_gate, take_over); the same ``required_attrs`` validator
guards against a kind silently losing a required attr, and is reused by the dashboard
integration test to check *real* emitted spans."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit

# milestone: llm→role/model/tokens/cost; tool→agent/tool/status; policy→rule_trace;
# human→decision/latency. node spans carry node-specific attrs (no universal key); world spans
# name their service.
REQUIRED_ATTRS: dict[str, set[str]] = {
    "llm": {"role", "provider", "model", "tokens_in", "tokens_out", "cost_usd"},
    "tool": {"agent", "tool", "status"},
    "policy": {"level", "rule_trace"},
    "human": {"decision", "human_review_seconds"},
    "node": set(),
    "world": {"service"},
}

# recorded fixtures — one representative row per kind, mirroring the real emit sites
FIXTURES: dict[str, dict[str, Any]] = {
    "llm": {
        "role": "supervisor",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "mode": "fake",
        "tokens_in": 10,
        "tokens_out": 5,
        "cost_usd": 0.0001,
    },
    "tool": {"agent": "log_analyst", "tool": "search_logs", "node": "log_analyst", "status": "OK"},
    "policy": {
        "level": "NOTIFY",
        "rule_trace": ["restart_service -> cache = NOTIFY"],
        "confidence": 0.9,
    },
    "human": {"decision": "takeover", "human_review_seconds": 42, "action_taken": "manual"},
    "node": {"steps": 3, "findings": 3},
    "world": {"service": "shopapi"},
}


def missing_attrs(kind: str, attrs: dict[str, Any]) -> set[str]:
    return REQUIRED_ATTRS.get(kind, set()) - set(attrs)


def test_every_kind_fixture_satisfies_contract() -> None:
    for kind, attrs in FIXTURES.items():
        assert missing_attrs(kind, attrs) == set(), (
            f"{kind} span missing {missing_attrs(kind, attrs)}"
        )


def test_validator_flags_a_missing_required_attr() -> None:
    broken = {k: v for k, v in FIXTURES["llm"].items() if k != "cost_usd"}
    assert missing_attrs("llm", broken) == {"cost_usd"}


@pytest.mark.parametrize("kind", sorted(REQUIRED_ATTRS))
def test_all_six_kinds_have_a_contract_and_fixture(kind: str) -> None:
    assert kind in FIXTURES  # every kind in 03 §1 (node|llm|tool|policy|human|world) is covered
