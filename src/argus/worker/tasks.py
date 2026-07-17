"""Celery tasks. M06: run_incident drives the graph until it completes or hits an
interrupt; on interrupt the task opens the PENDING approvals row and parks the incident at
WAITING_APPROVAL (side effects live here, not in the node, which re-runs on resume — 08
#18). resume_incident re-enters the same thread with the human's decision, guarded by an
idempotency check (08 #19)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_process_init
from langgraph.types import Command
from sqlalchemy import select

from argus.db.models import TERMINAL_STATUSES, Approval
from argus.db.session import session_scope
from argus.graph.runtime import get_compiled_graph
from argus.graph.support import escalation_field, now_iso, read_trace_id
from argus.obs import otel
from argus.obs.spans import span
from argus.policy.risk_gate import load_policy
from argus.repo import incidents as incident_repo
from argus.settings import get_settings
from argus.worker.app import celery_app

log = structlog.get_logger(__name__)

# Task-level wall-clock backstop (M08): the graph already escalates to take_over at the
# in-graph wall budget; these are the outer guardrails for a run that wedges *outside* the
# budget guard (e.g. a hung provider call). soft raises SoftTimeLimitExceeded (catchable →
# FAILED with a reason); hard kills the child as a last resort. acks_late (M02) means a
# hard-killed task is redelivered, and the idempotency checks make the re-run safe.
_MAX_WALL_S = int(load_policy().get("limits", {}).get("max_wall_seconds_per_incident", 420))
_SOFT_TIME_LIMIT_S = _MAX_WALL_S + 60
_HARD_TIME_LIMIT_S = _MAX_WALL_S + 120


@worker_process_init.connect
def _warm_graph(**_: Any) -> None:
    """Compile the graph + run the checkpointer .setup() once per worker child (08 #17), and
    wire OTel (adds the Jaeger sink only when OTEL_EXPORT_JAEGER=true — M09/ADR-07)."""
    otel.setup_tracing("argus-worker")
    try:
        get_compiled_graph()
    except Exception:  # DB may not be ready yet; the first task will retry lazily
        log.warning("graph.warm_failed", exc_info=True)


def _config(incident_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": incident_id}}


def _invoke_rooted(incident_id: str, trace_id: str, graph_input: Any) -> dict[str, Any]:
    """Run the graph inside one ``incident`` root span so every span an incident emits is a
    child of it (08 #24) — a single rooted trace for the UI and Jaeger. The root is registered
    while the graph runs so ``obs.spans`` auto-parents the node spans to it."""
    compiled = get_compiled_graph()
    with span("incident", "node", incident_id=incident_id, trace_id=trace_id) as root:
        otel.register_root(incident_id, root.span_id)
        try:
            return compiled.invoke(graph_input, config=_config(incident_id))
        finally:
            otel.clear_root(incident_id)


def _initial_state(incident_id: str, alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "alert": alert,
        "service_catalog": {},
        "memory_hits": [],
        "findings": [],
        "spec_llm_calls": [],
        "review_history": [],
        "remediation_attempts": [],
        "budget": {"llm_calls_used": 0, "started_at_iso": now_iso()},
    }


def _park_for_human(incident_id: str, payload: dict[str, Any]) -> None:
    """Open a PENDING approvals row + park the incident at WAITING_APPROVAL (idempotent)."""
    level = (
        "TAKE_OVER" if payload.get("kind") == "takeover" else payload.get("level", "APPROVE_ACTION")
    )
    with session_scope() as session:
        existing = session.scalars(
            select(Approval)
            .where(Approval.incident_id == incident_id, Approval.status == "PENDING")
            .order_by(Approval.created_at.desc())
        ).first()
        if existing is None:
            session.add(
                Approval(
                    incident_id=incident_id,
                    level=level,
                    status="PENDING",
                    proposed_action=payload.get("proposed_action") or {},
                    context=payload.get("context") or {},
                )
            )
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status != "WAITING_APPROVAL":
            incident_repo.transition(
                session,
                incident,
                "WAITING_APPROVAL",
                status_reason="awaiting human decision",
                **escalation_field(incident, level),
            )
    # eval mode: no human is watching, so decide as policy dictates and resume (07 §2)
    if get_settings().auto_approve == "policy_sim":
        _auto_decide_and_resume(incident_id)


def _auto_decide_and_resume(incident_id: str) -> None:
    """AUTO_APPROVE=policy_sim (07 §2): decide the just-parked approval automatically — approve
    the proposed remediation, or self-resolve a take_over — recorded ``decided_by=policy_sim``,
    then enqueue the resume. Real (human) mode leaves the row PENDING for the UI/API."""
    with session_scope() as session:
        approval = session.scalars(
            select(Approval)
            .where(Approval.incident_id == incident_id, Approval.status == "PENDING")
            .order_by(Approval.created_at.desc())
        ).first()
        if approval is None:
            return
        approval.status = "APPROVED"
        approval.decided_by = "policy_sim"
        approval.decided_at = datetime.now(UTC)
        if approval.level == "TAKE_OVER":
            # Record the graph's OWN hypothesis as the take-over root cause — a human taking over
            # writes down what the investigation concluded. A placeholder here would overwrite
            # incidents.root_cause and blind anything reading it (notably the eval judge, which
            # grades that column) to the agent's actual diagnosis, scoring RCA wrong on every
            # take-over. Fall back only when no hypothesis was formed.
            hypothesis = (approval.context or {}).get("hypothesis") or {}
            approval.modified_action = {
                "root_cause": hypothesis.get("root_cause")
                or "no confident hypothesis formed before take-over",
                "action_taken": "escalation recorded; no automated remediation (policy_sim)",
            }
        session.add(approval)
    resume_incident.delay(incident_id)


def _finalize(incident_id: str, result: dict[str, Any]) -> str:
    interrupts = result.get("__interrupt__")
    if interrupts:
        _park_for_human(incident_id, dict(interrupts[0].value))
        return "waiting_approval"
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        return incident.status if incident is not None else "unknown"


def _fail(incident_id: str, exc: Exception) -> str:
    log.exception("incident.graph_failed", incident_id=incident_id)
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status not in TERMINAL_STATUSES:
            incident_repo.transition(
                session, incident, "FAILED", status_reason=f"graph error: {exc}"
            )
    return "failed"


def _fail_timeout(incident_id: str) -> str:
    """Soft time-limit hit (M08): the run outlived max_wall + 60s. Mark FAILED with a clear
    reason rather than letting the generic handler label it a 'graph error'."""
    log.warning("incident.soft_timeout", incident_id=incident_id, limit_s=_SOFT_TIME_LIMIT_S)
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status not in TERMINAL_STATUSES:
            incident_repo.transition(
                session,
                incident,
                "FAILED",
                status_reason=f"wall-clock limit exceeded ({_SOFT_TIME_LIMIT_S}s task soft limit)",
            )
    return "failed"


@celery_app.task(
    name="argus.worker.tasks.run_incident",
    soft_time_limit=_SOFT_TIME_LIMIT_S,
    time_limit=_HARD_TIME_LIMIT_S,
)
def run_incident(incident_id: str) -> str:
    trace_id = uuid.uuid4().hex
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is None:
            log.warning("run_incident.unknown", incident_id=incident_id)
            return "unknown"
        alert = dict(incident.alert)
        incident.trace_id = trace_id  # the root span + intake reuse this one trace (08 #24)
        session.add(incident)

    log.info("run_incident.start", incident_id=incident_id)
    try:
        result = _invoke_rooted(incident_id, trace_id, _initial_state(incident_id, alert))
    except SoftTimeLimitExceeded:
        return _fail_timeout(incident_id)
    except Exception as exc:
        return _fail(incident_id, exc)
    status = _finalize(incident_id, result)
    log.info("run_incident.done", incident_id=incident_id, status=status)
    return status


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds())


def _resume_payload(incident_id: str, approval_id: str | None) -> dict[str, Any] | None:
    """Build the Command(resume=...) payload from the decided approvals row."""
    with session_scope() as session:
        approval = session.get(Approval, approval_id) if approval_id else None
        if approval is None:
            approval = session.scalars(
                select(Approval)
                .where(Approval.incident_id == incident_id, Approval.status != "PENDING")
                .order_by(Approval.created_at.desc())
            ).first()
        if approval is None or approval.status in ("PENDING", "AUTO", "ACK"):
            return None
        base = {
            "approval_id": str(approval.id),
            "comment": approval.decision_comment,
            "human_review_seconds": _seconds(approval.created_at, approval.decided_at),
        }
        if approval.level == "TAKE_OVER":
            resolution = approval.modified_action or {}
            return {
                **base,
                "kind": "takeover",
                "root_cause": resolution.get("root_cause"),
                "action_taken": resolution.get("action_taken"),
            }
        if approval.status == "MODIFIED":
            return {
                **base,
                "kind": "approval",
                "decision": "modify",
                "action": approval.modified_action,
            }
        if approval.status == "APPROVED":
            return {
                **base,
                "kind": "approval",
                "decision": "approve",
                "action": approval.proposed_action,
            }
        return {**base, "kind": "approval", "decision": "reject"}


@celery_app.task(
    name="argus.worker.tasks.resume_incident",
    soft_time_limit=_SOFT_TIME_LIMIT_S,
    time_limit=_HARD_TIME_LIMIT_S,
)
def resume_incident(incident_id: str, approval_id: str | None = None) -> str:
    # idempotency (08 #19): only a genuinely paused incident may resume
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is None:
            return "unknown"
        if incident.status != "WAITING_APPROVAL":
            log.info("resume_incident.noop", incident_id=incident_id, status=incident.status)
            return f"noop:{incident.status}"

    payload = _resume_payload(incident_id, approval_id)
    if payload is None:
        log.warning("resume_incident.no_decision", incident_id=incident_id)
        return "no_decision"

    log.info("resume_incident.start", incident_id=incident_id, decision=payload.get("decision"))
    try:
        # reuse the incident's existing trace so the resumed leg joins the same tree
        result = _invoke_rooted(incident_id, read_trace_id(incident_id), Command(resume=payload))
    except SoftTimeLimitExceeded:
        return _fail_timeout(incident_id)
    except Exception as exc:
        return _fail(incident_id, exc)
    status = _finalize(incident_id, result)
    log.info("resume_incident.done", incident_id=incident_id, status=status)
    return status
