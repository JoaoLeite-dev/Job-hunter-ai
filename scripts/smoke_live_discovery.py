"""Local PostgreSQL smoke: fake public API, real migration/cache, disposable schema."""

import os
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from job_hunter.application.live_discovery import cached_source, run_live
from job_hunter.application.search_configuration import (
    ConfigurationConflict,
    defaults,
    load_config,
    save_config,
)
from job_hunter.config import Settings
from job_hunter.infrastructure.db import Job, Match, Profile, SourceCache, VerifiedFact, utcnow
from job_hunter.infrastructure.remotive import SourceError

original = os.environ["DATABASE_URL"]
assert original.startswith("postgresql")
schema = "smoke_discovery_" + uuid4().hex
root = create_engine(original)
url = make_url(original).update_query_dict({"options": "-csearch_path=" + schema})
engine = create_engine(url)
try:
    with root.begin() as conn:
        conn.execute(CreateSchema(schema))
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with Session(engine) as db, db.begin():
        db.add(Profile(id="smoke-owner", name="Synthetic smoke profile"))
        db.flush()
        db.add(
            VerifiedFact(
                profile_id="smoke-owner",
                category="technical",
                claim="React",
                evidence_source="smoke only",
                verified_at=utcnow(),
            )
        )
    settings = replace(
        Settings.from_env(), discovery_mode="live", discovery_profile_id="smoke-owner"
    )
    item = {
        "id": 9001,
        "title": "Senior Frontend Engineer",
        "company_name": "Synthetic contract",
        "url": "https://remotive.com/remote-jobs/software-dev/synthetic-9001",
        "description": "<p>React</p>",
        "candidate_required_location": "LATAM",
        "tags": ["react"],
    }
    calls = []

    def fetch():
        calls.append(1)
        return {"jobs": [item]}

    assert run_live(engine, settings, fetch)["created"] == 1
    assert run_live(engine, settings, fetch)["duplicates"] == 1
    assert len(calls) == 1
    config = defaults(settings)
    config["markets"] = ["brazil"]
    with Session(engine) as db, db.begin():
        save_config(db, "smoke-owner", settings, 0, config)
    assert run_live(engine, settings, fetch)["matched_records"] == 0
    outcomes = []

    def save_competing_config():
        try:
            with Session(engine) as db, db.begin():
                save_config(db, "smoke-owner", settings, 1, config)
            outcomes.append("saved")
        except ConfigurationConflict:
            outcomes.append("conflict")

    contenders = [Thread(target=save_competing_config) for _ in range(2)]
    for contender in contenders:
        contender.start()
    for contender in contenders:
        contender.join(10)
    assert sorted(outcomes) == ["conflict", "saved"]
    with Session(engine) as db, db.begin():
        current = load_config(db, "smoke-owner", settings)
        save_config(db, "smoke-owner", settings, current["version"], defaults(settings))
    with Session(engine) as db, db.begin():
        assert db.scalar(select(Match)).profile_id == "smoke-owner"
        assert db.scalar(select(Job)).last_verified_at is not None
        cache = db.get(SourceCache, "remotive")
        cache.next_request_at = utcnow() - timedelta(seconds=1)
        cache.fetched_at = utcnow() - timedelta(days=1)
    entered, release = Event(), Event()
    results = []

    def slow_fetch():
        entered.set()
        assert release.wait(10)
        return {"jobs": [item]}

    def run_first():
        results.append(cached_source(engine, slow_fetch))

    worker = Thread(target=run_first)
    worker.start()
    assert entered.wait(5)
    try:
        try:
            cached_source(engine, lambda: (_ for _ in ()).throw(AssertionError("duplicate call")))
        except SourceError:
            pass
        else:
            raise AssertionError("Old cache was accepted")
    finally:
        release.set()
        worker.join(10)
    assert len(results) == 1 and not worker.is_alive()
    print(
        "POSTGRES_DISCOVERY_SMOKE_PASSED migration=0006 replay=ok "
        "cache_concurrency=ok config_concurrency=ok market_filter=ok stale=blocked"
    )
finally:
    engine.dispose()
    os.environ["DATABASE_URL"] = original
    with root.begin() as conn:
        conn.execute(DropSchema(schema, cascade=True))
    root.dispose()
