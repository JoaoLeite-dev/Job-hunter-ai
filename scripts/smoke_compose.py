"""Run inside the Compose API container, with DISCOVERY_MODE=fixture.

PowerShell: Get-Content -Raw scripts/smoke_compose.py |
    docker exec -i job-hunter-ai-api-1 python -
Uses only synthetic fixtures. Never sends mail or contacts external providers.
"""

import json
import os
import time
import urllib.request

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from job_hunter.infrastructure.db import AuditEvent, Job, Match, Outbox
from job_hunter.workers.celery_app import celery

assert os.environ["DISCOVERY_MODE"] == "fixture"
assert os.environ["DATABASE_URL"].startswith("postgresql")
base = "http://127.0.0.1:5000"
headers = {"Authorization": "Bearer " + os.environ["API_TOKEN"]}


def request(path, method="GET"):
    req = urllib.request.Request(base + path, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == 200
        return json.load(response)


assert request("/health/ready")["status"] == "ready"
first = request("/api/v1/discovery/run", "POST")
second = request("/api/v1/discovery/run", "POST")
assert first["created"] + first["duplicates"] == 3
assert second["created"] == 0 and second["duplicates"] == 3
jobs = request("/api/v1/jobs")["items"]
assert len(jobs) == 3
assert sum(request("/api/v1/jobs/" + j["id"] + "/match")["hard_gate"] for j in jobs) == 2
assert celery.control.ping(timeout=3), "Worker did not answer through Redis"
engine = create_engine(os.environ["DATABASE_URL"])
with Session(engine) as session:
    count_before = session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.event_type == "discovery.completed")
    )
celery.send_task("job_hunter.discovery")
for _ in range(40):
    with Session(engine) as session:
        count_after = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "discovery.completed")
        )
    if count_after > count_before:
        break
    time.sleep(0.25)
else:
    raise AssertionError("Worker did not complete the queued discovery")
with Session(engine) as session:
    for table in [Job, Match, Outbox]:
        assert session.scalar(select(func.count()).select_from(table)) == 3
engine.dispose()
print("PASS: PostgreSQL, HTTP replay, matching, outbox, Redis and Celery worker")
