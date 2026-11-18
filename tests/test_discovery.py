import pytest
from sqlalchemy import func, select

from job_hunter.application.discovery import Discovery
from job_hunter.application.fixtures import DEMO_JOBS, fixture_source
from job_hunter.application.matching import Fact, canonicalize, eligibility, score
from job_hunter.infrastructure.db import (
    AuditEvent,
    Job,
    Match,
    Outbox,
    Profile,
    VerifiedFact,
    utcnow,
)


def test_normalization():
    assert (
        canonicalize("https://Jobs.EXAMPLE.org/1/?utm_source=x#top") == "https://jobs.example.org/1"
    )
    for url in [
        "http://example.org",
        "file:///etc/passwd",
        "https://localhost/a",
        "https://10.0.0.1/a",
        "https://example.org:9000/a",
    ]:
        with pytest.raises(ValueError):
            canonicalize(url)


def test_eligibility_and_unverified_facts():
    assert eligibility(DEMO_JOBS[0])["status"] == "eligible"
    assert eligibility(DEMO_JOBS[1])["status"] == "blocked"
    assert eligibility(DEMO_JOBS[2])["status"] == "needs_review"
    facts = [Fact("1", "technical", "React", True), Fact("2", "technical", "Terraform", False)]
    result = score(DEMO_JOBS[0], facts)
    assert result["score"] == 35
    assert result["requirements"][1]["status"] == "unknown"
    assert result["requirements"][1]["evidence_fact_ids"] == []
    assert score(DEMO_JOBS[1], facts)["hard_gate"]
    assert score({**DEMO_JOBS[0], "status": "expired"}, facts)["hard_gate"]


def test_discovery_transaction_and_replay(app):
    with app.extensions["session_factory"].begin() as session:
        profile = Profile(name="Synthetic test profile")
        session.add(profile)
        session.flush()
        profile_id = profile.id
        session.add(
            VerifiedFact(
                profile_id=profile_id,
                category="technical",
                claim="React",
                evidence_source="synthetic fixture",
                verified_at=utcnow(),
            )
        )

    def failed_source():
        raise RuntimeError("secret must not be persisted")

    with app.extensions["session_factory"].begin() as session:
        result = Discovery(session).run(
            profile_id, {"broken": failed_source, "demo": fixture_source}
        )
        assert result["created"] == 3
        assert result["failed_sources"] == ["broken"]
    with app.extensions["session_factory"].begin() as session:
        replay = Discovery(session).run(profile_id, {"demo": fixture_source})
        assert replay["created"] == 0
        assert replay["duplicates"] == 3
        assert session.scalar(select(func.count()).select_from(Job)) == 3
        assert session.scalar(select(func.count()).select_from(Match)) == 3
        assert session.scalar(select(func.count()).select_from(Outbox)) == 3
        events = session.scalars(select(AuditEvent)).all()
        assert "secret" not in str([e.payload_redacted for e in events])


def test_failed_transaction_rolls_back_jobs_and_outbox(app):
    with app.extensions["session_factory"].begin() as session:
        session.add(Profile(id="test-profile", name="Synthetic"))
    with pytest.raises(RuntimeError), app.extensions["session_factory"].begin() as session:
        # Force a write in the outer transaction before SAVEPOINTs (SQLite test behavior).
        session.add(AuditEvent(actor="test", entity_id="test", event_type="started"))
        session.flush()
        Discovery(session).run("test-profile", {"demo": fixture_source})
        raise RuntimeError("rollback")
    with app.extensions["session_factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(Outbox)) == 0


def test_demo_api_auth_and_gate(app):
    client = app.test_client()
    assert client.post("/api/v1/discovery/run").status_code == 401
    assert (
        client.post(
            "/api/v1/discovery/run", headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 409
    )


def test_demo_api_replay_and_match(app):
    from dataclasses import replace

    from job_hunter import create_app

    demo = create_app(replace(app.extensions["settings"], discovery_mode="fixture"))
    client = demo.test_client()
    headers = {"Authorization": "Bearer test-token"}
    assert client.post("/api/v1/discovery/run", headers=headers).json["created"] == 3
    assert client.post("/api/v1/discovery/run", headers=headers).json["duplicates"] == 3
    jobs = client.get("/api/v1/jobs", headers=headers).json["items"]
    assert len(jobs) == 3
    for job in jobs:
        result = client.get(f"/api/v1/jobs/{job['id']}/match", headers=headers)
        assert result.status_code == 200
        assert 0 <= result.json["score"] <= 100
    assert client.get("/api/v1/jobs/missing/match", headers=headers).status_code == 404
    demo.extensions["db_engine"].dispose()


def test_cli_demo(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["demo"])
    assert result.exit_code == 0
    assert '"created": 3' in result.output


def test_scheduler_configuration_and_disabled_task(monkeypatch):
    monkeypatch.setenv("DISCOVERY_MODE", "disabled")
    from job_hunter.workers.celery_app import celery
    from job_hunter.workers.tasks import discover

    assert celery.conf.timezone == "America/Bahia"
    assert celery.conf.beat_schedule["daily-discovery"]["task"] == "job_hunter.discovery"
    assert discover.run() == {"status": "not_configured", "sent": 0}
