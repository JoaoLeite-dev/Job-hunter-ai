"""PostgreSQL smoke for Sheets outbox; fake provider, isolated disposable schema.

Run inside the API container: docker exec -i job-hunter-ai-api-1 python -
No Google credentials or outbound requests are used.
"""

import os
from datetime import timedelta
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from job_hunter.application.demo import run_demo
from job_hunter.application.sheets_sync import sync
from job_hunter.infrastructure.db import Job, Outbox, utcnow
from job_hunter.infrastructure.sheets import SheetsError


class Projection:
    def __init__(self):
        self.rows = {}
        self.fail_once = True

    def ensure_tabs(self):
        pass

    def upsert(self, tab, values):
        self.rows[(tab, values[0])] = values
        if self.fail_once:
            self.fail_once = False
            raise SheetsError("transport_uncertain", retryable=True)

    def close(self):
        pass


original_url = os.environ["DATABASE_URL"]
assert original_url.startswith("postgresql")
schema = "smoke_sheets_" + uuid4().hex
root_engine = create_engine(original_url)
test_url = make_url(original_url).update_query_dict({"options": "-csearch_path=" + schema})
engine = create_engine(test_url)
projection = Projection()
try:
    with root_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with Session(engine) as session, session.begin():
        run_demo(session)
    with Session(engine) as session, session.begin():
        result = sync(session, projection)
        assert result["processed"] == 2 and result["failed"] == 1
    with Session(engine) as session, session.begin():
        failed = session.scalar(select(Outbox).where(Outbox.processed_at.is_(None)))
        failed.next_attempt_at = utcnow() - timedelta(seconds=1)
    with Session(engine) as session, session.begin():
        assert sync(session, projection)["processed"] == 1
    assert len(projection.rows) == 3
    # Two independent database transactions: only one owns the projection writer lock.
    with Session(engine) as first, first.begin():
        assert not sync(first, projection)["busy"]
        with Session(engine) as second, second.begin():
            assert sync(second, projection)["busy"]
    # Simulate a process crash after provider success but before DB commit.
    with Session(engine) as session, session.begin():
        job = session.scalar(select(Job))
        session.add(Outbox(entity_id=job.id, event_type="job.changed", payload={}))
    try:
        with Session(engine) as session, session.begin():
            assert sync(session, projection)["processed"] == 1
            raise RuntimeError("simulated crash")
    except RuntimeError:
        pass
    with Session(engine) as session, session.begin():
        assert sync(session, projection)["processed"] == 1
        assert all(event.processed_at for event in session.scalars(select(Outbox)))
    assert len(projection.rows) == 3
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    command.check(cfg)
    print("PASS: PostgreSQL migration, Sheets retry, rollback replay and concurrent writer lock")
finally:
    os.environ["DATABASE_URL"] = original_url
    engine.dispose()
    # Drop only the unique schema created by this smoke, never the application schema.
    assert schema.startswith("smoke_sheets_") and len(schema) == len("smoke_sheets_") + 32
    with root_engine.begin() as connection:
        connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    root_engine.dispose()
