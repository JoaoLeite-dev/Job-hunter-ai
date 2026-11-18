import hmac
from uuid import uuid4

from flask import Flask, g, jsonify, request
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from job_hunter.config import Settings
from job_hunter.infrastructure.db import Job


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.extensions["db_engine"] = engine
    app.extensions["session_factory"] = sessionmaker(engine)
    app.extensions["settings"] = settings
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

    return app
