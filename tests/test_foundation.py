import pytest
from alembic import command
from alembic.config import Config

from job_hunter import create_app
from job_hunter.config import Settings
from job_hunter.domain.states import Status, transition


def test_health_auth_and_empty_jobs(app):
    client = app.test_client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v1/jobs").status_code == 401
    response = client.get("/api/v1/jobs", headers={"Authorization": "Bearer test-token"})
    assert response.json == {"items": []}
    assert response.headers["X-Correlation-ID"]


def test_readiness_without_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    app = create_app()
    assert app.test_client().get("/health/ready").status_code == 503
    app.extensions["db_engine"].dispose()


@pytest.mark.parametrize("target", [Status.APPROVED, Status.QUEUED, Status.SENT])
def test_sensitive_transitions_require_authorization(target):
    current = {
        Status.APPROVED: Status.READY_FOR_REVIEW,
        Status.QUEUED: Status.APPROVED,
        Status.SENT: Status.QUEUED,
    }[target]
    with pytest.raises(ValueError):
        transition(current, target)


def test_invalid_transition():
    with pytest.raises(ValueError):
        transition(Status.DISCOVERED, Status.SENT, authorized=True)
    assert transition(Status.DISCOVERED, Status.ELIGIBLE) == Status.ELIGIBLE


def test_real_delivery_disabled(monkeypatch):
    monkeypatch.setenv("EMAIL_SEND_ENABLED", "true")
    with pytest.raises(ValueError, match="not implemented"):
        Settings.from_env()


def test_migrations_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration.db'}")
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
