from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(100), default="America/Bahia")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceCache(Base):
    __tablename__ = "source_cache"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    next_request_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))


class VerifiedFact(Base):
    __tablename__ = "verified_facts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    category: Mapped[str] = mapped_column(String(100))
    claim: Mapped[str] = mapped_column(Text)
    evidence_source: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(String(200))
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    company: Mapped[str] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="unknown")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("job_id", "profile_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    score: Mapped[int] = mapped_column(Integer)
    hard_gate: Mapped[bool]
    evidence: Mapped[dict] = mapped_column(JSON)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "profile_id", "recipient"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    status: Mapped[str] = mapped_column(String(40), default="discovered")
    recipient: Mapped[str | None] = mapped_column(String(320))
    package_hash: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    payload_redacted: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Outbox(Base):
    __tablename__ = "sync_outbox"
    __table_args__ = (
        Index("ix_sync_outbox_pending", "processed_at", "next_attempt_at", "attempts"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    terminal_failure: Mapped[bool] = mapped_column(default=False, server_default=false())


class ResumeTemplate(Base):
    __tablename__ = "resume_templates"
    __table_args__ = (UniqueConstraint("profile_id", "sha256", name="uq_resume_profile_sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(default=False)


class ResumeVariant(Base):
    __tablename__ = "resume_variants"
    __table_args__ = (
        UniqueConstraint("job_id", "template_id", "request_hash", name="uq_variant_request"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    template_id: Mapped[str] = mapped_column(ForeignKey("resume_templates.id"))
    request_hash: Mapped[str] = mapped_column(String(64))
    docx_key: Mapped[str] = mapped_column(Text)
    pdf_key: Mapped[str | None] = mapped_column(Text)
    sha256_docx: Mapped[str] = mapped_column(String(64))
    sha256_pdf: Mapped[str | None] = mapped_column(String(64))
    edits_json: Mapped[list] = mapped_column(JSON)
    evidence_json: Mapped[list] = mapped_column(JSON)
    validation_json: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(40), default="validation_pending")
