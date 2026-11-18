from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from job_hunter import create_app
from job_hunter.application.search_configuration import (
    ConfigurationError,
    accepts,
    defaults,
    market_for,
    select_records,
    validate_config,
)
from job_hunter.infrastructure.db import AuditEvent, Job, SourceCache, utcnow
from tests.test_live_discovery import record, setup_profile
from tests.test_web_dashboard import login

HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def live(app):
    instance = create_app(setup_profile(app))
    instance.extensions["public_source_fetch"] = Mock(
        return_value={
            "jobs": [
                record(
                    id=i,
                    url=f"https://remotive.com/remote-jobs/software-dev/frontend-{i}",
                    candidate_required_location=location,
                )
                for i, location in enumerate(["Brazil", "Worldwide", "USA", "Remote"], 1)
            ]
        }
    )
    yield instance
    instance.extensions["db_engine"].dispose()


@pytest.mark.parametrize(
    ("location", "market"),
    [
        ("Brazil", "brazil"),
        ("Brasil", "brazil"),
        ("Remote Brazil", "brazil"),
        ("Worldwide", "international"),
        ("LATAM", "international"),
        ("Brazil, USA", "international"),
        ("USA", "international"),
        ("Remote", "unknown"),
        ("", "unknown"),
    ],
)
def test_market_scope_independent_of_brazil_eligibility(location, market):
    assert market_for({"source_location": location, "allowed_countries": ["BR"]}) == market


def test_keywords_scope_combination_exclusions_and_accents(app):
    config = defaults(app.extensions["settings"])
    config["title_terms"] = ["front end"]
    job = {
        "title": "Sênior Front-end Engineer",
        "description": "React with TypeScript",
        "source_location": "Brazil",
        "remote": True,
        "allowed_countries": ["BR"],
        "eligibility_evidence": "provider",
    }
    assert accepts(job, config)
    config["keywords"] = ["React", "Python"]
    assert accepts(job, config)
    config["keyword_mode"] = "all"
    assert not accepts(job, config)
    config["keywords"] = ["senior"]
    assert accepts(job, config)
    config["keyword_scope"] = "title"
    config["keywords"] = ["React"]
    assert not accepts(job, config)
    config["keywords"] = []
    config["excluded_titles"] = ["senior"]
    assert not accepts(job, config)
    config["excluded_titles"] = []
    config["excluded_keywords"] = ["engineer"]
    assert not accepts(job, config)
    config["excluded_keywords"] = ["engine"]
    assert accepts(job, config)  # Literal word boundaries, not arbitrary substrings.


def test_market_specific_terms_locations_and_eligibility(app):
    config = defaults(app.extensions["settings"])
    config["brazil_keywords"] = ["React"]
    config["international_keywords"] = ["Python"]
    payload = {"jobs": [record(candidate_required_location="Brazil")]}
    assert len(select_records(payload, config, utcnow().isoformat())) == 1
    payload["jobs"][0]["candidate_required_location"] = "Worldwide"
    assert select_records(payload, config, utcnow().isoformat()) == []
    config["international_keywords"] = []
    config["locations"] = ["LATAM"]
    assert select_records(payload, config, utcnow().isoformat()) == []
    config["locations"] = []
    config["eligible_only"] = True
    assert len(select_records(payload, config, utcnow().isoformat())) == 1
    payload["jobs"][0]["candidate_required_location"] = "USA"
    assert select_records(payload, config, utcnow().isoformat()) == []


def test_junior_exclusion_is_editable_and_not_hardcoded(app):
    config = defaults(app.extensions["settings"])
    payload = {"jobs": [record(title="Junior Frontend Engineer")]}
    assert select_records(payload, config, utcnow().isoformat()) == []
    config["excluded_titles"] = []
    assert len(select_records(payload, config, utcnow().isoformat())) == 1


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("sources", ["https://localhost"]),
        ("sources", ["linkedin"]),
        ("markets", ["arbitrary"]),
        ("markets", []),
        ("title_terms", []),
        ("keywords", ["x" * 81]),
        ("keywords", ["a\nb"]),
        ("keywords", ["a"] * 41),
        ("enabled", 1),
        ("keyword_mode", "regex"),
        ("keyword_scope", "url"),
    ],
)
def test_configuration_rejects_unsupported_or_unbounded_input(app, key, value):
    config = defaults(app.extensions["settings"])
    config[key] = value
    with pytest.raises(ConfigurationError):
        validate_config(config, app.extensions["settings"])


def test_save_persists_version_conflicts_and_audit(live):
    client = live.test_client()
    initial = client.get("/api/v1/search-settings", headers=HEADERS).json
    assert initial["version"] == 0 and initial["sources"][0]["id"] == "remotive"
    config = initial["config"]
    config["keywords"] = [" React ", "react"]
    result = client.put(
        "/api/v1/search-settings", headers=HEADERS, json={"version": 0, "config": config}
    )
    assert result.status_code == 200
    assert result.json["version"] == 1 and result.json["config"]["keywords"] == ["React"]
    assert (
        client.put(
            "/api/v1/search-settings", headers=HEADERS, json={"version": 0, "config": config}
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/v1/search-settings", headers=HEADERS, json={"version": 1, "config": config}
        ).json["version"]
        == 2
    )
    assert (
        client.put(
            "/api/v1/search-settings", headers=HEADERS, json={"version": 1, "config": config}
        ).status_code
        == 409
    )
    other = create_app(replace(live.extensions["settings"], discovery_roles="Backend"))
    try:
        assert other.test_client().get("/api/v1/search-settings", headers=HEADERS).json["config"][
            "keywords"
        ] == ["React"]
    finally:
        other.extensions["db_engine"].dispose()
    with live.extensions["session_factory"]() as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "search.configuration_saved")
            )
        )
        assert len(events) == 2


def test_settings_and_preview_are_private_and_csrf_protected(live):
    client = live.test_client()
    assert client.get("/api/v1/search-settings").status_code == 401
    state = login(client)
    initial = client.get("/api/v1/search-settings").json
    body = {"version": 0, "config": initial["config"]}
    assert client.put("/api/v1/search-settings", json=body).status_code == 403
    assert client.post("/api/v1/search-settings/preview", json=initial["config"]).status_code == 403
    assert (
        client.put(
            "/api/v1/search-settings", json=body, headers={"X-CSRF-Token": state["csrf_token"]}
        ).status_code
        == 200
    )


def test_saved_rules_drive_real_run_pause_and_cache_preview(live):
    client = live.test_client()
    assert client.post("/api/v1/discovery/run", headers=HEADERS).json["created"] == 4
    initial = client.get("/api/v1/search-settings", headers=HEADERS).json
    config = deepcopy(initial["config"])
    config["markets"] = ["brazil"]
    assert (
        client.post("/api/v1/search-settings/preview", headers=HEADERS, json=config).json["matched"]
        == 1
    )
    assert client.get("/api/v1/search-settings", headers=HEADERS).json["version"] == 0
    assert (
        client.put(
            "/api/v1/search-settings", headers=HEADERS, json={"version": 0, "config": config}
        ).status_code
        == 200
    )
    result = client.post("/api/v1/discovery/run", headers=HEADERS).json
    assert result["matched_records"] == 1 and result["search_config_version"] == 1
    config["enabled"] = False
    assert (
        client.put(
            "/api/v1/search-settings", headers=HEADERS, json={"version": 1, "config": config}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/discovery/run", headers=HEADERS).json["paused"]
    live.extensions["public_source_fetch"].assert_called_once()
    with live.extensions["session_factory"]() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 4  # History preserved.
    jobs = client.get("/api/v1/dashboard", headers=HEADERS).json["jobs"]
    assert {j["market"] for j in jobs} == {"brazil", "international", "unknown"}


def test_preview_without_cache_never_fetches_and_empty_sources_pause(live):
    client = live.test_client()
    initial = client.get("/api/v1/search-settings", headers=HEADERS).json
    assert (
        client.post(
            "/api/v1/search-settings/preview", headers=HEADERS, json=initial["config"]
        ).status_code
        == 409
    )
    initial["config"]["sources"] = []
    assert (
        client.put(
            "/api/v1/search-settings",
            headers=HEADERS,
            json={"version": 0, "config": initial["config"]},
        ).status_code
        == 200
    )
    assert client.post("/api/v1/discovery/run", headers=HEADERS).json["paused"]
    live.extensions["public_source_fetch"].assert_not_called()
    with live.extensions["session_factory"]() as db:
        assert db.get(SourceCache, "remotive") is None


def test_scheduled_worker_uses_same_saved_configuration(live, monkeypatch):
    from job_hunter.workers import tasks

    settings = live.extensions["settings"]
    client = live.test_client()
    initial = client.get("/api/v1/search-settings", headers=HEADERS).json
    initial["config"]["enabled"] = False
    client.put(
        "/api/v1/search-settings", headers=HEADERS, json={"version": 0, "config": initial["config"]}
    )
    monkeypatch.setattr(tasks.Settings, "from_env", lambda: settings)
    assert tasks.discover.run()["paused"]
