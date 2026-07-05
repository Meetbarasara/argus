"""alertwatch — evaluates config/alert_rules.yaml over worldstate metrics every 10s.

A rule fires after ``for_checks`` consecutive breaching evaluations, then respects a
per-(rule, service, dep) refire cooldown. Fired alerts are always appended to
alerts/sent.jsonl (the world's test oracle) and POSTed to the platform webhook
best-effort. The rule engine (evaluate_rule / check_rules / AlertWatcher.tick) is pure
and unit-tested on the host.
"""

from __future__ import annotations

import operator
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml

from demoworld.common import settings
from demoworld.common.jsonlog import append_jsonl, now_iso, read_jsonl

OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le, "==": operator.eq}
HEARTBEAT = Path("/tmp/heartbeat")  # noqa: S108 - container-local liveness marker


@dataclass
class Rule:
    name: str
    metric: str
    op: str
    threshold: float
    for_checks: int
    severity: str


@dataclass
class Breach:
    rule: Rule
    service: str
    dep: str | None
    value: Any


def evaluate_rule(rule: Rule, value: Any) -> bool:
    try:
        return bool(OPS[rule.op](float(value), float(rule.threshold)))
    except (KeyError, TypeError, ValueError):
        return False


def latest_values(lines: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Latest metric line per (service, name, labels) series."""
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for line in lines:
        key = (
            line.get("service"),
            line.get("name"),
            tuple(sorted((line.get("labels") or {}).items())),
        )
        latest[key] = line
    return latest


def check_rules(rules: list[Rule], latest: dict[tuple[Any, ...], dict[str, Any]]) -> list[Breach]:
    out: list[Breach] = []
    for rule in rules:
        for (service, name, labels_key), line in latest.items():
            if name != rule.metric:
                continue
            if evaluate_rule(rule, line.get("value")):
                dep = dict(labels_key).get("dep")
                out.append(Breach(rule, str(service), dep, line.get("value")))
    return out


def build_alert(breach: Breach, ts: str) -> dict[str, Any]:
    dep = breach.dep
    tag = f"[{dep}]" if dep else ""
    return {
        "alert_id": "a-" + uuid4().hex[:6],
        "rule": breach.rule.name,
        "service": breach.service,
        "severity": breach.rule.severity,
        "ts": ts,
        "window_seconds": 60,
        "observed": {
            "metric": breach.rule.metric,
            "value": breach.value,
            "threshold": breach.rule.threshold,
        },
        "labels": {"dep": dep} if dep else {},
        "summary": (
            f"{breach.service} {breach.rule.metric}{tag}={breach.value} "
            f"breached {breach.rule.op} {breach.rule.threshold}"
        ),
    }


class AlertWatcher:
    """Consecutive-breach + cooldown state machine over successive metric snapshots."""

    def __init__(self, rules: list[Rule], cooldown_s: float = 600.0) -> None:
        self.rules = rules
        self.cooldown_s = cooldown_s
        self.consecutive: dict[tuple[str, str, str | None], int] = {}
        self.last_fired: dict[tuple[str, str, str | None], float] = {}

    def tick(self, lines: list[dict[str, Any]], now: float, ts: str) -> list[dict[str, Any]]:
        breaches = {
            (b.rule.name, b.service, b.dep): b
            for b in check_rules(self.rules, latest_values(lines))
        }
        # reset series that are no longer breaching
        for key in self.consecutive:
            if key not in breaches:
                self.consecutive[key] = 0
        fired: list[dict[str, Any]] = []
        for key, breach in breaches.items():
            self.consecutive[key] = self.consecutive.get(key, 0) + 1
            if self.consecutive[key] >= breach.rule.for_checks:
                last = self.last_fired.get(key)
                if last is None or (now - last) >= self.cooldown_s:
                    fired.append(build_alert(breach, ts))
                    self.last_fired[key] = now
        return fired


def load_config(path: str | Path) -> tuple[list[Rule], float, float]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = [
        Rule(
            name=r["name"],
            metric=r["metric"],
            op=r["op"],
            threshold=r["threshold"],
            for_checks=r["for_checks"],
            severity=r["severity"],
        )
        for r in data["rules"]
    ]
    return (
        rules,
        float(data.get("evaluation_interval_seconds", 10)),
        float(data.get("refire_cooldown_seconds", 600)),
    )


def fire(alert: dict[str, Any], webhook_url: str, sent_file: Path) -> None:
    append_jsonl(sent_file, alert)  # always record — the world's alert oracle
    if not webhook_url:
        return
    for _ in range(3):
        try:
            with httpx.Client(timeout=3.0) as client:
                client.post(webhook_url, json=alert).raise_for_status()
            return
        except Exception:
            time.sleep(0.5)


def main() -> None:
    rules_path = os.environ.get("ALERT_RULES_PATH", "config/alert_rules.yaml")
    rules, interval, cooldown = load_config(rules_path)
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "")
    metrics_file = settings.metrics_file()
    sent_file = settings.worldstate_path() / "alerts" / "sent.jsonl"
    watcher = AlertWatcher(rules, cooldown_s=cooldown)
    while True:
        lines = read_jsonl(metrics_file, limit=600)
        for alert in watcher.tick(lines, time.monotonic(), now_iso()):
            fire(alert, webhook, sent_file)
        HEARTBEAT.write_text(str(time.time()))
        time.sleep(interval)


if __name__ == "__main__":
    main()
