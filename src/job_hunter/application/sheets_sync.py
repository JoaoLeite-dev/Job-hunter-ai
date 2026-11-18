"""Idempotent outbox consumer. PostgreSQL owns state; Sheets is a projection."""

import json
from datetime import timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from job_hunter.infrastructure.db import Application, AuditEvent, Job, Match, Outbox, utcnow
from job_hunter.infrastructure.sheets import SheetsError, SheetsGateway

MAX_ATTEMPTS = 5
# One projection writer per PostgreSQL database, across API and all workers.
LOCK_ID = 647310031


def iso(value) -> str:
    return value.isoformat() if value else ""


def project(session: Session, event: Outbox) -> tuple[str, list]:
    if event.event_type.startswith("job."):
        job = session.get(Job, event.entity_id)
        if not job:
            raise SheetsError("projection_entity_missing")
        match = session.scalar(select(Match).where(Match.job_id == job.id).order_by(Match.id))
        data = job.data
        requirements = match.evidence.get("requirements", []) if match else []
        gaps = [r["requirement"] for r in requirements if r["status"] != "met"]
        return "Vagas", [
            job.id,
            iso(job.discovered_at),
            job.company,
            job.title,
            ", ".join(data.get("allowed_countries", [])),
            str(data.get("remote", "unknown")),
            data.get("contract_type", ""),
            json.dumps(data.get("salary", {}), ensure_ascii=False),
            ", ".join(data.get("requirements", {}).get("technical", [])),
            match.score if match else "",
            match.hard_gate if match else True,
            ", ".join(gaps),
            job.canonical_url,
            iso(job.last_verified_at),
            job.status,
            "",
            "",
            iso(utcnow()),
        ]
    if event.event_type.startswith("application."):
        application = session.get(Application, event.entity_id)
        if not application:
            raise SheetsError("projection_entity_missing")
        # Approval and delivery details will be populated by their future domain models.
        return "Candidaturas", [
            application.id,
            application.job_id,
            application.recipient or "",
            "",
            "",
            "",
            "",
            "",
            application.status,
            "",
        ]
    raise SheetsError("unsupported_outbox_event")


def sync(session: Session, gateway: SheetsGateway, *, limit: int = 25) -> dict:
    if not 1 <= limit <= 500:
        raise ValueError("Sync limit must be between 1 and 500")
    summary = {"processed": 0, "failed": 0, "busy": False}
    if session.get_bind().dialect.name == "postgresql":
        locked = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID})
        if not locked:
            return {**summary, "busy": True}
    now = utcnow()
    events = list(
        session.scalars(
            select(Outbox)
            .where(
                Outbox.processed_at.is_(None),
                Outbox.attempts < MAX_ATTEMPTS,
                Outbox.terminal_failure.is_(False),
                or_(Outbox.next_attempt_at.is_(None), Outbox.next_attempt_at <= now),
            )
            .order_by(Outbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not events:
        return summary
    # A schema/credential error is recorded on each selected event with sanitized codes.
    setup_error = None
    try:
        gateway.ensure_tabs()
    except SheetsError as error:
        setup_error = error
    for event in events:
        event.attempts += 1
        try:
            if setup_error:
                raise setup_error
            tab, values = project(session, event)
            gateway.upsert(tab, values)
        except SheetsError as error:
            event.last_error_code = error.code
            event.next_attempt_at = now + timedelta(seconds=min(3600, 30 * 2**event.attempts))
            if not error.retryable:
                event.terminal_failure = True
            summary["failed"] += 1
            session.add(
                AuditEvent(
                    actor="sheets",
                    entity_id=event.entity_id,
                    event_type="sheets.failed",
                    payload_redacted={"code": error.code, "attempts": event.attempts},
                )
            )
        else:
            event.processed_at = utcnow()
            event.last_error_code = None
            event.next_attempt_at = None
            summary["processed"] += 1
            session.add(
                AuditEvent(
                    actor="sheets",
                    entity_id=event.entity_id,
                    event_type="sheets.processed",
                    payload_redacted={},
                )
            )
    session.flush()
    return summary


def retry_failed(session: Session) -> int:
    events = session.scalars(
        select(Outbox).where(
            Outbox.processed_at.is_(None),
            or_(Outbox.attempts >= MAX_ATTEMPTS, Outbox.terminal_failure.is_(True)),
        )
    )
    count = 0
    for event in events:
        event.attempts = 0
        event.terminal_failure = False
        event.next_attempt_at = None
        event.last_error_code = None
        count += 1
    session.add(
        AuditEvent(
            actor="operator",
            entity_id="outbox",
            event_type="sheets.retry_requested",
            payload_redacted={"count": count},
        )
    )
    return count
