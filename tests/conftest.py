import pytest
from alembic import command
from alembic.config import Config

from job_hunter import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("EMAIL_SEND_ENABLED", "false")
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app()
    yield app
    app.extensions["db_engine"].dispose()
