from job_hunter.workers.celery_app import celery


@celery.task(name="job_hunter.discovery")
def discover() -> dict:
    return {"status": "not_configured", "sent": 0}
