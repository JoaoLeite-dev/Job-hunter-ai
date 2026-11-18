"""Publication dates, never discovery/refresh dates, define the listing window."""

from datetime import UTC, datetime, timedelta

from job_hunter.infrastructure.db import utcnow

MAX_AGE_DAYS = 30


def publication_time(value):
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def is_recent(value, now=None):
    now = now or utcnow()
    published = publication_time(value)
    return published is not None and now - timedelta(days=MAX_AGE_DAYS) <= published <= now
