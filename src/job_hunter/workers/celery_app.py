from celery import Celery
from celery.schedules import crontab

from job_hunter.config import Settings

settings = Settings.from_env()
celery = Celery("job_hunter", broker=settings.redis_url, include=["job_hunter.workers.tasks"])
minute, hour, day, month, weekday = settings.cron.split()
celery.conf.update(
    timezone=settings.timezone,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "daily-discovery": {
            "task": "job_hunter.discovery",
            "schedule": crontab(
                minute=minute, hour=hour, day_of_month=day, month_of_year=month, day_of_week=weekday
            ),
        }
    },
)
