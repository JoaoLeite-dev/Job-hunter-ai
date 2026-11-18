from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from job_hunter import create_app
from job_hunter.application.live_discovery import cached_source, run_live
from job_hunter.application.matching import eligibility
from job_hunter.infrastructure.db import (
    AuditEvent,
    Job,
    Match,
    Profile,
    SourceCache,
    VerifiedFact,
    utcnow,
)
from job_hunter.infrastructure.remotive import (
    NoRedirect,
    SourceError,
    fetch_public_jobs,
    normalize_jobs,
)


def record(**changes):
    return {
        "id": 1,
        "title": "Senior Frontend Engineer",
        "company_name": "Source contract fixture",
        "url": "https://remotive.com/remote-jobs/software-dev/frontend-1",
        "description": "<p>Build React interfaces &amp; test.</p><script>do not display</script>",
        "candidate_required_location": "LATAM",
        "tags": ["react", "Typescript "],
        "publication_date": utcnow().isoformat(),
        **changes,
    }


def setup_profile(app):
    with app.extensions["session_factory"].begin() as db:
        db.add(Profile(id="owner", name="Synthetic contract profile"))
        db.flush()
        db.add(
            VerifiedFact(
                profile_id="owner",
                category="technical",
                claim="React",
                evidence_source="test",
                verified_at=utcnow(),
            )
        )
    return replace(app.extensions["settings"], discovery_mode="live", discovery_profile_id="owner")


@pytest.mark.parametrize(
    ("location", "description", "expected"),
    [
        ("Worldwide", "", "eligible"),
        ("Brazil", "", "eligible"),
        ("LATAM, Europe, USA", "", "eligible"),
        ("USA, Canada", "", "blocked"),
        ("Europe", "", "blocked"),
        ("Remote", "", "needs_review"),
        ("Worldwide", "US residents only", "needs_review"),
        ("LATAM", "Must be based in the United States", "needs_review"),
    ],
)
def test_provider_location_is_conservative(location, description, expected):
    job = normalize_jobs(
        {"jobs": [record(candidate_required_location=location, description=description)]},
        "frontend",
        utcnow().isoformat(),
    )[0]
    assert eligibility(job)["status"] == expected


def test_normalization_filters_html_and_untrusted_links():
    payload = {
        "jobs": [
            record(),
            record(id=2, title="Junior Frontend"),
            record(id=3, title="Sales"),
            record(id=4, url="https://localhost/a"),
            record(id=5, url="https://evil.example/a"),
            record(id=6, title="Senior Full-stack Engineer"),
        ]
    }
    jobs = normalize_jobs(payload, "frontend,full stack", utcnow().isoformat())
    assert len(jobs) == 2
    assert jobs[0]["description"] == "Build React interfaces & test."
    assert jobs[0]["requirements"]["technical"] == ["React", "TypeScript"]
    assert jobs[0]["requirement_basis"] == "provider_tags"
    with pytest.raises(SourceError):
        normalize_jobs({"jobs": {}}, "frontend", utcnow().isoformat())


def test_public_http_bounded_payload_and_no_redirects(monkeypatch):
    import job_hunter.infrastructure.remotive as source

    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.side_effect = [b'{"jobs": []}', b""]
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(source, "build_opener", lambda *args: opener)
    assert fetch_public_jobs() == {"jobs": []}
    assert opener.open.call_args.args[0].full_url == source.ENDPOINT
    response.read.side_effect = [b"x" * 11]
    monkeypatch.setattr(source, "MAX_BYTES", 10)
    with pytest.raises(SourceError):
        fetch_public_jobs()
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "http://localhost") is None


def test_live_replay_profile_evidence_and_source_changes(app):
    settings = setup_profile(app)
    fetch = Mock(return_value={"jobs": [record()]})
    engine = app.extensions["db_engine"]
    first = run_live(engine, settings, fetch)
    assert first["created"] == 1 and not first["cached"]
    second = run_live(engine, settings, fetch)
    assert second["created"] == 0 and second["duplicates"] == 1 and second["cached"]
    assert fetch.call_count == 1
    with app.extensions["session_factory"].begin() as db:
        job = db.scalar(select(Job))
        identity = job.id
        assert job.last_verified_at and job.source_id == "remotive"
        match = db.scalar(select(Match))
        assert match.profile_id == "owner" and match.score == 35
        cache = db.get(SourceCache, "remotive")
        cache.next_request_at = utcnow() - timedelta(seconds=1)
    fetch.return_value = {
        "jobs": [
            record(
                candidate_required_location="USA",
                title="Senior Frontend Developer",
                url="https://remotive.com/remote-jobs/software-dev/updated-1",
            )
        ]
    }
    updated = run_live(engine, settings, fetch)
    assert updated["updated"] == 1 and updated["created"] == 0
    with app.extensions["session_factory"]() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        job = db.get(Job, identity)
        assert job.title == "Senior Frontend Developer"
        assert job.canonical_url.endswith("/updated-1")
        assert eligibility(job.data)["status"] == "blocked"
        assert db.scalar(select(Match)).hard_gate


def test_failure_budget_stale_cache_and_audit_do_not_leak(app):
    settings = setup_profile(app)
    engine = app.extensions["db_engine"]
    fetch = Mock(side_effect=RuntimeError("secret content"))
    for _ in range(2):
        with pytest.raises(SourceError):
            run_live(engine, settings, fetch)
    assert fetch.call_count == 1
    with app.extensions["session_factory"].begin() as db:
        state = db.get(SourceCache, "remotive")
        state.payload = {"jobs": [record()]}
        state.fetched_at = utcnow() - timedelta(days=1)
        assert "secret" not in str([e.payload_redacted for e in db.scalars(select(AuditEvent))])
    with pytest.raises(SourceError, match="source_cache_stale"):
        run_live(engine, settings, fetch)
    with app.extensions["session_factory"]() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_concurrent_callers_share_provider_budget(app):
    engine = app.extensions["db_engine"]
    entered, release = Event(), Event()
    results = []

    def fetch():
        entered.set()
        assert release.wait(5)
        return {"jobs": []}

    def first():
        results.append(cached_source(engine, fetch))

    worker = Thread(target=first)
    worker.start()
    assert entered.wait(5)
    try:
        with pytest.raises(SourceError):
            cached_source(engine, Mock(side_effect=AssertionError("second request")))
    finally:
        release.set()
        worker.join(5)
    assert len(results) == 1 and not worker.is_alive()


def test_live_api_auth_and_no_profile_prevents_external_fetch(app):
    settings = replace(app.extensions["settings"], discovery_mode="live")
    live = create_app(settings)
    fetch = Mock(return_value={"jobs": [record()]})
    live.extensions["public_source_fetch"] = fetch
    client = live.test_client()
    assert client.post("/api/v1/discovery/run").status_code == 401
    assert (
        client.post(
            "/api/v1/discovery/run", headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 409
    )
    fetch.assert_not_called()
    live.extensions["db_engine"].dispose()


def test_live_api_returns_real_profile_and_source(app):
    live = create_app(setup_profile(app))
    live.extensions["public_source_fetch"] = Mock(return_value={"jobs": [record()]})
    client = live.test_client()
    headers = {"Authorization": "Bearer test-token"}
    assert client.post("/api/v1/discovery/run", headers=headers).json["created"] == 1
    data = client.get("/api/v1/dashboard", headers=headers).json
    job = data["jobs"][0]
    assert not job["is_demo"] and job["source_name"] == "Remotive"
    assert job["score"] == 35 and job["verified_at"]
    live.extensions["db_engine"].dispose()
