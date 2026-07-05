import pytest

from argus.repo.incidents import STATE_TRANSITIONS, can_transition

pytestmark = pytest.mark.unit

ALL_STATUSES = {
    "OPEN",
    "INVESTIGATING",
    "WAITING_APPROVAL",
    "REMEDIATING",
    "RECOVERED",
    "RESOLVED",
    "TAKEN_OVER",
    "FAILED",
}
TERMINAL = {"RESOLVED", "TAKEN_OVER", "FAILED"}
ACTIVE = ALL_STATUSES - TERMINAL


def test_all_statuses_defined():
    assert set(STATE_TRANSITIONS) == ALL_STATUSES


def test_terminal_states_have_no_exits():
    for term in TERMINAL:
        assert STATE_TRANSITIONS[term] == set()


def test_every_target_is_a_known_status():
    for targets in STATE_TRANSITIONS.values():
        assert targets <= ALL_STATUSES


def test_happy_path_transitions_are_legal():
    assert can_transition("OPEN", "INVESTIGATING")
    assert can_transition("INVESTIGATING", "WAITING_APPROVAL")
    assert can_transition("WAITING_APPROVAL", "INVESTIGATING")
    assert can_transition("WAITING_APPROVAL", "REMEDIATING")
    assert can_transition("INVESTIGATING", "REMEDIATING")
    assert can_transition("REMEDIATING", "RECOVERED")
    assert can_transition("REMEDIATING", "INVESTIGATING")
    assert can_transition("RECOVERED", "RESOLVED")


def test_takeover_and_fail_reachable_from_every_active_state():
    for state in ACTIVE:
        assert can_transition(state, "TAKEN_OVER")
        assert can_transition(state, "FAILED")


def test_illegal_transitions_rejected():
    assert not can_transition("OPEN", "RESOLVED")
    assert not can_transition("OPEN", "REMEDIATING")
    assert not can_transition("INVESTIGATING", "RECOVERED")
    assert not can_transition("INVESTIGATING", "RESOLVED")
    assert not can_transition("RECOVERED", "REMEDIATING")
    assert not can_transition("RESOLVED", "INVESTIGATING")
    assert not can_transition("FAILED", "INVESTIGATING")
    assert not can_transition("TAKEN_OVER", "RESOLVED")
