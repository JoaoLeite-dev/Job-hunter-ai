from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from job_hunter.application.live_discovery import run_live
from job_hunter.application.publication import is_recent, publication_time
from job_hunter.application.search_configuration import defaults, save_config
from job_hunter.infrastructure.brazilian_boards import (
    fetch_board,
    parse_listings,
    queries_for,
    robots_allow,
)
from job_hunter.infrastructure.db import Job, utcnow
from job_hunter.infrastructure.remotive import SourceError
from tests.test_live_discovery import record, setup_profile

HEADERS = {"Authorization": "Bearer test-token"}
INFOJOBS = """<div class="js_cardLink" data-id="123" data-href="/vaga-de-frontend__123.aspx">
<div class="js_date" data-value="2026/11/13 03:29:00">
</div>
<h2 class="js_vacancyTitle">Senior Frontend</h2>
<a href="/empresa-test__2.aspx">Synthetic Company</a>
<div class="mb-8">São Paulo - SP</div>
<div class="d-inline-flex flex-wrap mb-8">Home Office</div>
<p>React TypeScript</p>
<script>alert('ignore')</script>
</div>"""
VAGAS = """<li class="vaga">
<a class="link-detalhes-vaga" data-id-vaga="234" href="/vagas/v234/frontend">Senior Frontend</a>
<span class="emprVaga">Synthetic Company</span>
<div class="detalhes">React role</div>
<div class="vaga-local">São Paulo / SP</div>
<span class="data-publicacao">26/10/2026</span>
</li>"""


def test_thirty_day_window_uses_publication_never_discovery():
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    assert is_recent((now - timedelta(days=30)).isoformat(), now)
    assert not is_recent((now - timedelta(days=30, seconds=1)).isoformat(), now)
    assert not is_recent((now + timedelta(seconds=1)).isoformat(), now)
    assert not is_recent(None, now) and not is_recent("yesterday", now)
    assert publication_time("2026-11-18T09:00:00-03:00") == now


def test_listing_apis_and_metrics_hide_old_unknown_and_future(app):
    now = utcnow()
    with app.extensions["session_factory"].begin() as db:
        for i, delta in enumerate([1, 31, None, -1]):
            db.add(
                Job(
                    id=str(i),
                    source_id="test",
                    external_id=str(i),
                    canonical_url=f"https://example.org/{i}",
                    company="Synthetic",
                    title="Frontend",
                    description="",
                    data={"published_at": now.isoformat()},
                    published_at=now - timedelta(days=delta) if delta is not None else None,
                )
            )
    client = app.test_client()
    rows = client.get("/api/v1/jobs", headers=HEADERS).json["items"]
    assert [row["id"] for row in rows] == ["0"]
    data = client.get("/api/v1/dashboard", headers=HEADERS).json
    assert data["stats"]["jobs"] == 1 and data["publication_policy"]["hidden"] == 3
    assert [row["id"] for row in data["jobs"]] == ["0"]
    with app.extensions["session_factory"]() as db:
        assert len(list(db.scalars(select(Job)))) == 4  # History was not destroyed.


def test_parsers_preserve_source_dates_and_do_not_infer_remote_from_description():
    job = parse_listings("infojobs", INFOJOBS.encode())[0]
    assert job["published_at"] == "2026-11-13T03:29:00-03:00"
    assert job["remote"] is True and job["source_location"] == "Brazil"
    assert "alert" not in job["description"]
    assert job["requirements"]["technical"] == ["React", "TypeScript"]
    job = parse_listings("vagas", VAGAS.encode())[0]
    assert job["published_at"] == "2026-10-26T00:00:00-03:00"
    assert job["remote"] is None
    absent = INFOJOBS.replace("2026/11/13 03:29:00", "Ontem").replace("Home Office", "Presencial")
    job = parse_listings("infojobs", absent.encode())[0]
    assert job["published_at"] == "" and job["remote"] is False
    assert (
        parse_listings(
            "infojobs",
            INFOJOBS.replace("/vaga-de-frontend__123.aspx", "https://evil.example/job").encode(),
        )
        == []
    )
    with pytest.raises(SourceError, match="layout"):
        parse_listings("infojobs", b"<html>Security challenge</html>")


def test_robot_rules_specificity_wildcards_and_fail_closed():
    robots = b"User-agent: *\nAllow: /\nDisallow: /private*\nAllow: /private/public$\n"
    assert not robots_allow(robots, "https://example.org/private?a=1")
    assert robots_allow(robots, "https://example.org/private/public")
    assert not robots_allow(robots, "https://example.org/private/public/extra")
    assert not robots_allow(
        b"User-agent: *\nAllow: /\nUser-agent: JobHunterAI\nDisallow: /", "https://example.org/a"
    )
    with pytest.raises(SourceError):
        robots_allow(b"<html>Blocked</html>", "https://example.org/a")


def test_fetcher_stops_on_robots_and_never_follows_job_links(app, monkeypatch):
    import job_hunter.infrastructure.brazilian_boards as board

    config = defaults(app.extensions["settings"])
    config["title_terms"] = ["frontend", "front-end", "backend", "fullstack", "react native"]
    assert queries_for(config) == ["frontend", "backend", "fullstack"]
    read = Mock(return_value=b"User-agent: *\nDisallow: /")
    monkeypatch.setattr(board, "read_public", read)
    with pytest.raises(SourceError, match="robots_disallowed"):
        fetch_board("infojobs", config)
    assert read.call_count == 1
    config["title_terms"] = ["frontend"]
    read.side_effect = [b"User-agent: *\nAllow: /", INFOJOBS.encode()]
    data = fetch_board("infojobs", config)
    assert len(data["jobs"]) == 1 and data["normalized"]
    assert (
        read.call_count == 3
    )  # Two calls this run: robots and search; no details, profiles or login.


def test_partial_source_failure_retains_success_and_independent_cache(app):
    settings = setup_profile(app)
    config = defaults(settings)
    config["sources"] = ["remotive", "infojobs", "vagas"]
    with app.extensions["session_factory"].begin() as db:
        save_config(db, "owner", settings, 0, config)
    item = parse_listings("infojobs", INFOJOBS.encode())[0]
    item["published_at"] = utcnow().isoformat()

    def board(source, config):
        if source == "vagas":
            raise SourceError("source_access_blocked")
        return {"jobs": [item], "normalized": True, "queries": ["frontend", "backend", "fullstack"]}

    result = run_live(
        app.extensions["db_engine"], settings, Mock(return_value={"jobs": [record()]}), board
    )
    assert result["created"] == 2 and result["failed_sources"] == ["vagas"]
    assert len(result["sources"]) == 2
    replay = run_live(
        app.extensions["db_engine"],
        settings,
        Mock(side_effect=AssertionError("network")),
        Mock(side_effect=AssertionError("network")),
    )
    assert replay["cached"] and replay["duplicates"] == 2
    assert replay["failed_sources"] == ["vagas"]


def test_old_or_undated_feed_items_are_not_imported(app):
    settings = setup_profile(app)
    data = {
        "jobs": [
            record(publication_date=(utcnow() - timedelta(days=31)).isoformat()),
            record(id=2, publication_date=""),
        ]
    }
    result = run_live(app.extensions["db_engine"], settings, lambda: data)
    assert result["matched_records"] == 0
