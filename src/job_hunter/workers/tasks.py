from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from job_hunter.application.demo import run_demo
from job_hunter.application.live_discovery import run_live
from job_hunter.config import Settings
from job_hunter.infrastructure.remotive import SourceError
from job_hunter.workers.celery_app import celery


@celery.task(name="job_hunter.discovery")
def discover() -> dict:
    settings = Settings.from_env()
    if settings.discovery_mode not in {"fixture", "live"}:
        return {"status": "not_configured", "sent": 0}
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        if settings.discovery_mode == "live":
            try:
                return run_live(engine, settings)
            except SourceError as error:
                return {"status": "source_failed", "code": str(error), "sent": 0}
        with Session(engine) as session, session.begin():
            return run_demo(session)
    finally:
        engine.dispose()


@celery.task(name="job_hunter.sheets_sync")
def sync_sheets() -> dict:
    from job_hunter.application.sheets_sync import sync
    from job_hunter.infrastructure.sheets import GoogleSheets, SheetsError

    settings = Settings.from_env()
    if not settings.sheets_sync_enabled:
        return {"status": "disabled"}
    try:
        gateway = GoogleSheets.from_env()
    except (SheetsError, ValueError):
        return {"status": "not_configured"}
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            return sync(session, gateway)
    finally:
        engine.dispose()
        gateway.close()
