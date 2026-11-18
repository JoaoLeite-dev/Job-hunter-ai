from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from job_hunter import create_app
from job_hunter.application.demo import run_demo
from job_hunter.application.sheets_sync import MAX_ATTEMPTS, retry_failed, sync
from job_hunter.infrastructure.db import Application, AuditEvent, Job, Outbox, utcnow
from job_hunter.infrastructure.sheets import HEADERS, GoogleSheets, SheetsError
from tests.sheets_fake import SheetsTransport


@pytest.fixture
def gateway():
    return GoogleSheets("test-spreadsheet-id", SheetsTransport())


@pytest.fixture
def seeded(app):
    with app.extensions["session_factory"].begin() as session:
        run_demo(session)
    return app.extensions["session_factory"]


def test_tabs_and_upsert_contract(gateway):
    gateway.ensure_tabs()
    gateway.ensure_tabs()
    assert set(gateway.transport.tabs) == set(HEADERS)
    row = ["stable-id", '=HYPERLINK("evil")'] + [""] * (len(HEADERS["Vagas"]) - 2)
    gateway.upsert("Vagas", row)
    row[2] = "updated company"
    gateway.upsert("Vagas", row)
    assert gateway.transport.tabs["Vagas"] == [HEADERS["Vagas"], row]
    creates = [call for call in gateway.transport.calls if call[1].endswith(":batchUpdate")]
    assert len(creates) == 1


def test_header_mismatch_and_existing_duplicate_block_writes(gateway):
    gateway.ensure_tabs()
    gateway.transport.tabs["Vagas"][0] = ["unrecognized header"]
    with pytest.raises(SheetsError, match="sheet_header_mismatch"):
        gateway.ensure_tabs()
    gateway.transport.tabs["Vagas"] = [HEADERS["Vagas"], ["dup"], ["dup"]]
    with pytest.raises(SheetsError, match="duplicate_sheet_id"):
        gateway.upsert("Vagas", ["dup"] + [""] * (len(HEADERS["Vagas"]) - 1))


def test_projection_and_replay(seeded, gateway):
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 3
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 0
        assert all(e.processed_at for e in session.scalars(select(Outbox)))
        assert all(j.status in {"active", "unknown"} for j in session.scalars(select(Job)))
    assert len(gateway.transport.tabs["Vagas"]) == 4
    assert any(row[10] is True for row in gateway.transport.tabs["Vagas"][1:])
    assert "Terraform" in str(gateway.transport.tabs["Vagas"])


def test_timeout_after_success_reuses_row(seeded, gateway):
    gateway.ensure_tabs()
    gateway.transport.lose_next_write = True
    with seeded.begin() as session:
        result = sync(session, gateway)
        assert result["failed"] == 1
        assert result["processed"] == 2
    with seeded.begin() as session:
        failed = session.scalar(select(Outbox).where(Outbox.processed_at.is_(None)))
        assert failed.attempts == 1
        assert failed.last_error_code == "transport_uncertain"
        assert failed.next_attempt_at is not None
        # Retry is deferred until backoff expires.
        assert sync(session, gateway)["processed"] == 0
        failed.next_attempt_at = utcnow() - timedelta(seconds=1)
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 1
        assert "secret-token" not in str(
            [e.payload_redacted for e in session.scalars(select(AuditEvent))]
        )
    assert len(gateway.transport.tabs["Vagas"]) == 4


def test_rollback_after_remote_write_is_idempotent(seeded, gateway):
    with pytest.raises(RuntimeError), seeded.begin() as session:
        sync(session, gateway)
        raise RuntimeError("crash before database commit")
    assert len(gateway.transport.tabs["Vagas"]) == 4
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 3
    assert len(gateway.transport.tabs["Vagas"]) == 4


@pytest.mark.parametrize("status", [429, 503])
def test_retry_budget(seeded, gateway, status):
    gateway.transport.status = status
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with seeded.begin() as session:
            for event in session.scalars(select(Outbox)):
                event.next_attempt_at = None
            session.flush()
            assert sync(session, gateway)["failed"] == 3
            assert all(e.attempts == attempt for e in session.scalars(select(Outbox)))
    with seeded.begin() as session:
        assert sync(session, gateway)["failed"] == 0
        assert retry_failed(session) == 3
    gateway.transport.status = 200
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 3


def test_permanent_error_needs_operator_retry(seeded, gateway):
    gateway.transport.status = 403
    with seeded.begin() as session:
        assert sync(session, gateway)["failed"] == 3
        assert all(e.terminal_failure and e.attempts == 1 for e in session.scalars(select(Outbox)))
    gateway.transport.status = 200
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 0
        assert retry_failed(session) == 3
        session.flush()
        assert sync(session, gateway)["processed"] == 3


def test_application_projection_preserves_state(seeded, gateway):
    with seeded.begin() as session:
        job = session.scalar(select(Job))
        from job_hunter.application.demo import DEMO_PROFILE_ID

        application = Application(
            job_id=job.id,
            profile_id=DEMO_PROFILE_ID,
            recipient="published@example.org",
            status="ready_for_review",
        )
        session.add(application)
        session.flush()
        session.add(Outbox(entity_id=application.id, event_type="application.changed", payload={}))
    with seeded.begin() as session:
        assert sync(session, gateway)["processed"] == 4
        assert session.scalar(select(Application)).status == "ready_for_review"
    assert len(gateway.transport.tabs["Candidaturas"]) == 2


def test_auth_disabled_and_configured_endpoint(app, gateway):
    client = app.test_client()
    path = "/api/v1/integrations/sheets/sync"
    headers = {"Authorization": "Bearer test-token"}
    assert client.post(path).status_code == 401
    assert client.post(path, headers=headers).status_code == 409
    configured = create_app(replace(app.extensions["settings"], sheets_sync_enabled=True))
    configured.extensions["sheets_gateway_factory"] = lambda: gateway
    with configured.extensions["session_factory"].begin() as session:
        run_demo(session)
    response = configured.test_client().post(path, headers=headers)
    assert response.status_code == 200
    assert response.json["processed"] == 3
    assert gateway.transport.closed
    configured.extensions["db_engine"].dispose()


def test_oauth_missing_config_fails_without_network(monkeypatch):
    for key in [
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    ]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SheetsError, match="sheets_credentials_missing"):
        GoogleSheets.from_env()


def test_oauth_refresh_setup_uses_only_sheets_scope(monkeypatch):
    for key in [
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    ]:
        monkeypatch.setenv(key, "synthetic-test-value")
    gateway = GoogleSheets.from_env()
    assert list(gateway.transport.credentials.scopes) == [
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    gateway.close()


def test_invalid_response_is_sanitized():
    transport = Mock()
    transport.request.return_value.status_code = 200
    transport.request.return_value.json.side_effect = ValueError("private-provider-body")
    with pytest.raises(SheetsError, match="invalid_provider_response") as result:
        GoogleSheets("test-spreadsheet-id", transport).ensure_tabs()
    assert "private" not in str(result.value)


def test_migration_preserves_pending_outbox(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "0001")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sync_outbox (id, entity_id, event_type, payload, attempts) "
                "VALUES ('pending', 'job-id', 'job.discovered', '{}', 0)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT attempts, terminal_failure FROM sync_outbox")).one()
        assert row == (0, 0)
    command.check(cfg)
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    engine.dispose()


def test_sheets_worker_disabled(monkeypatch):
    monkeypatch.setenv("SHEETS_SYNC_ENABLED", "false")
    from job_hunter.workers.tasks import sync_sheets

    assert sync_sheets.run() == {"status": "disabled"}
