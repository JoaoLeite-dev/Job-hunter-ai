from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_hunter.application.demo import run_demo
from job_hunter.config import Settings
from job_hunter.workers.celery_app import celery


@celery.task(name="job_hunter.discovery")
def discover() -> dict:
    settings = Settings.from_env()
    if settings.discovery_mode != "fixture":
        return {"status": "not_configured", "sent": 0}
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            return run_demo(session)
    finally:
        engine.dispose()
