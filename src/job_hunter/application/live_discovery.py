"""Local orchestration with a database-coordinated six-hour provider budget."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_hunter.application.demo import DEMO_PROFILE_ID
from job_hunter.application.discovery import Discovery
from job_hunter.application.search_configuration import load_config, select_records
from job_hunter.infrastructure.db import AuditEvent, Profile, ResumeTemplate, SourceCache, utcnow
from job_hunter.infrastructure.remotive import SourceError, fetch_public_jobs

SOURCE_ID = "remotive"
INTERVAL = timedelta(hours=6)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def profile_id_for(session, configured=""):
    if configured:
        if configured == DEMO_PROFILE_ID or not session.get(Profile, configured):
            raise SourceError("discovery_profile_missing")
        return configured
    ids = set(session.scalars(select(ResumeTemplate.profile_id).where(ResumeTemplate.active)))
    ids.discard(DEMO_PROFILE_ID)
    if len(ids) != 1:
        raise SourceError("discovery_profile_missing")
    return ids.pop()


def cached_source(engine, fetch=fetch_public_jobs, now=None):
    now = now or utcnow()
    # Seed once, then claim with one atomic conditional UPDATE. Works across API/worker.
    with Session(engine) as db, db.begin():
        if not db.get(SourceCache, SOURCE_ID):
            try:
                with db.begin_nested():
                    db.add(
                        SourceCache(id=SOURCE_ID, next_request_at=datetime(1970, 1, 1, tzinfo=UTC))
                    )
                    db.flush()
            except IntegrityError:
                pass
        claimed = (
            db.execute(
                update(SourceCache)
                .where(
                    SourceCache.id == SOURCE_ID,
                    SourceCache.next_request_at <= now,
                )
                .values(next_request_at=now + INTERVAL)
            ).rowcount
            == 1
        )
    if claimed:
        try:
            payload = fetch()
            from job_hunter.infrastructure.remotive import validate_payload

            validate_payload(payload)
        except Exception:
            with Session(engine) as db, db.begin():
                db.get(SourceCache, SOURCE_ID).error_code = "source_unavailable"
        else:
            with Session(engine) as db, db.begin():
                state = db.get(SourceCache, SOURCE_ID)
                state.payload, state.fetched_at, state.error_code = payload, now, None
    with Session(engine) as db:
        state = db.get(SourceCache, SOURCE_ID)
        if state.payload is None or state.fetched_at is None:
            raise SourceError("source_unavailable_or_busy")
        stale = now - aware(state.fetched_at) >= INTERVAL
        if stale:
            # Old evidence must not refresh job verification dates or eligibility.
            raise SourceError("source_cache_stale")
        return state.payload, {
            "source": "Remotive",
            "cached": not claimed,
            "fetched_at": aware(state.fetched_at).isoformat(),
            "next_request_at": aware(state.next_request_at).isoformat(),
        }


def run_live(engine, settings, fetch=fetch_public_jobs):
    with Session(engine) as db:
        profile_id = profile_id_for(db, settings.discovery_profile_id)
        preferences = load_config(db, profile_id, settings)
    config = preferences["config"]
    if not config["enabled"] or not config["sources"]:
        return {
            "created": 0,
            "duplicates": 0,
            "matched_records": 0,
            "paused": True,
            "search_config_version": preferences["version"],
        }
    try:
        payload, metadata = cached_source(engine, fetch)
    except SourceError as error:
        with Session(engine) as db, db.begin():
            db.add(
                AuditEvent(
                    actor="discovery",
                    entity_id=SOURCE_ID,
                    event_type="source_failed",
                    payload_redacted={"code": str(error)},
                )
            )
        raise
    records = select_records(payload, config, metadata["fetched_at"])
    with Session(engine) as db, db.begin():
        result = Discovery(db).run(profile_id, {SOURCE_ID: lambda: records})
        db.add(
            AuditEvent(
                actor="discovery",
                entity_id=profile_id,
                event_type="search.executed",
                payload_redacted={
                    "configuration_version": preferences["version"],
                    "matched_records": len(records),
                },
            )
        )
    return {
        **result,
        **metadata,
        "matched_records": len(records),
        "profile_id": profile_id,
        "search_config_version": preferences["version"],
    }
