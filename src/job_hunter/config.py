import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    api_token: str
    timezone: str
    cron: str
    email_send_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        timezone = os.getenv("JOB_SEARCH_TIMEZONE", "America/Bahia")
        ZoneInfo(timezone)
        cron = os.getenv("JOB_SEARCH_CRON", "0 8 * * *")
        if len(cron.split()) != 5:
            raise ValueError("JOB_SEARCH_CRON must contain five fields")
        # This release has no delivery adapter: enabling delivery must fail closed.
        if os.getenv("EMAIL_SEND_ENABLED", "false").lower() != "false":
            raise ValueError(
                "Real email delivery is not implemented; keep EMAIL_SEND_ENABLED=false"
            )
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///var/local.db"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            api_token=os.getenv("API_TOKEN", ""),
            timezone=timezone,
            cron=cron,
        )
