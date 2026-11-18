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
    discovery_mode: str = "disabled"
    sheets_sync_enabled: bool = False
    resume_storage_root: str = "var/private/resumes"
    match_prepare_threshold: int = 75
    resume_render_enabled: bool = False
    libreoffice_binary: str = "/usr/bin/libreoffice"

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
        threshold = int(os.getenv("MATCH_PREPARE_THRESHOLD", "75"))
        if not 0 <= threshold <= 100:
            raise ValueError("Invalid match threshold")
        return cls(
            match_prepare_threshold=threshold,
            resume_render_enabled=os.getenv("RESUME_RENDER_ENABLED", "false").lower() == "true",
            libreoffice_binary=os.getenv("LIBREOFFICE_BINARY", "/usr/bin/libreoffice"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///var/local.db"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            api_token=os.getenv("API_TOKEN", ""),
            timezone=timezone,
            cron=cron,
            discovery_mode=os.getenv("DISCOVERY_MODE", "disabled"),
            resume_storage_root=os.getenv("RESUME_STORAGE_ROOT", "var/private/resumes"),
            sheets_sync_enabled=os.getenv("SHEETS_SYNC_ENABLED", "false").lower() == "true",
        )
