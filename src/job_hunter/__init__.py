import hmac
from uuid import uuid4

import click
from flask import Flask, g, jsonify, request
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from job_hunter.api.resumes import blueprint as resume_blueprint
from job_hunter.api.resumes import profile_create, resume_import, resume_inspect
from job_hunter.application.demo import run_demo
from job_hunter.application.sheets_sync import retry_failed, sync
from job_hunter.config import Settings
from job_hunter.infrastructure.db import Job, Match
from job_hunter.infrastructure.sheets import GoogleSheets, SheetsError


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.extensions["db_engine"] = engine
    app.extensions["session_factory"] = sessionmaker(engine)
    app.extensions["settings"] = settings
    app.extensions["sheets_gateway_factory"] = GoogleSheets.from_env
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.before_request
    def authenticate():
        g.correlation_id = str(uuid4())
        if request.path.startswith("/api/"):
            expected = settings.api_token
            provided = request.headers.get("Authorization", "")
            if not expected or not hmac.compare_digest(provided, f"Bearer {expected}"):
                return jsonify(error="unauthorized"), 401

    @app.after_request
    def correlation(response):
        response.headers["X-Correlation-ID"] = g.correlation_id
        return response

    @app.get("/health/live")
    def live():
        return jsonify(status="ok")

    @app.get("/health/ready")
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM alembic_version"))
        except Exception:
            return jsonify(status="unavailable"), 503
        return jsonify(status="ready")

    @app.get("/api/v1/jobs")
    def jobs():
        with app.extensions["session_factory"]() as session:
            rows = session.scalars(select(Job).order_by(Job.id).limit(100))
            return jsonify(
                items=[
                    {
                        "id": j.id,
                        "title": j.title,
                        "company": j.company,
                        "canonical_url": j.canonical_url,
                        "status": j.status,
                    }
                    for j in rows
                ]
            )

    @app.post("/api/v1/discovery/run")
    def discovery_run():
        if settings.discovery_mode != "fixture":
            return jsonify(error="discovery_not_configured"), 409
        with app.extensions["session_factory"].begin() as session:
            return jsonify(run_demo(session))

    @app.get("/api/v1/jobs/<job_id>/match")
    def job_match(job_id):
        with app.extensions["session_factory"]() as session:
            result = session.scalar(select(Match).where(Match.job_id == job_id))
            if result is None:
                return jsonify(error="match_not_found"), 404
            return jsonify(result.evidence)

    @app.cli.command("demo")
    def demo():
        """Run a synthetic offline discovery batch; never sends email."""
        import json

        import click

        with app.extensions["session_factory"].begin() as session:
            click.echo(json.dumps(run_demo(session)))

    @app.post("/api/v1/integrations/sheets/sync")
    def sheets_sync():
        if not settings.sheets_sync_enabled:
            return jsonify(error="sheets_sync_disabled"), 409
        try:
            gateway = app.extensions["sheets_gateway_factory"]()
        except (SheetsError, ValueError):
            return jsonify(error="sheets_not_configured"), 409
        try:
            with app.extensions["session_factory"].begin() as session:
                result = sync(session, gateway)
            return jsonify(result), 409 if result["busy"] else 200
        finally:
            gateway.close()

    @app.cli.command("sheets-sync")
    @click.option(
        "--retry-failed",
        "retry",
        is_flag=True,
        help="Requeue failed events after correcting the cause.",
    )
    def sheets_sync_cli(retry):
        import json

        import click

        if not settings.sheets_sync_enabled:
            raise click.ClickException("Sheets sync is disabled")
        try:
            gateway = app.extensions["sheets_gateway_factory"]()
        except (SheetsError, ValueError):
            raise click.ClickException("Sheets is not configured") from None
        try:
            with app.extensions["session_factory"].begin() as session:
                if retry:
                    retry_failed(session)
                result = sync(session, gateway)
            click.echo(json.dumps(result))
        finally:
            gateway.close()

    app.register_blueprint(resume_blueprint)
    for command in [profile_create, resume_import, resume_inspect]:
        app.cli.add_command(command)
    return app
