import pytest
from pydantic import ValidationError

from argus.api.schemas import AlertPayload

pytestmark = pytest.mark.unit


def test_valid_alert_defaults():
    a = AlertPayload(
        alert_id="a-1",
        rule="high_error_rate",
        service="shopapi",
        severity="critical",
        ts="2026-07-05T00:00:00Z",
    )
    assert a.service == "shopapi"
    assert a.window_seconds == 60
    assert a.observed == {}


def test_extra_fields_are_kept():
    a = AlertPayload(
        alert_id="a-1",
        rule="r",
        service="s",
        severity="critical",
        ts="t",
        labels={"dep": "redis"},
        note="extra",
    )
    dumped = a.model_dump()
    assert dumped["labels"] == {"dep": "redis"}
    assert dumped["note"] == "extra"


def test_missing_required_fields_raise():
    with pytest.raises(ValidationError):
        AlertPayload(rule="r", service="s")  # missing alert_id, severity, ts
