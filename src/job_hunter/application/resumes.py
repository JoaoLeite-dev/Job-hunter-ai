"""Template registration and explicit field authorization; no CV generation or factual approval."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_hunter.infrastructure.db import AuditEvent, Profile, ResumeTemplate, utcnow
from job_hunter.infrastructure.resumes import ResumeError, approve_manifest, store_template


def import_template(
    session: Session, storage_root: Path, source: Path, profile_id: str
) -> tuple[ResumeTemplate, bool]:
    if not session.get(Profile, profile_id):
        raise ResumeError("profile_not_found")
    storage_key, manifest = store_template(storage_root, source)
    existing = session.scalar(
        select(ResumeTemplate).where(
            ResumeTemplate.profile_id == profile_id,
            ResumeTemplate.sha256 == manifest["template_sha256"],
        )
    )
    if existing:
        return existing, False
    template = ResumeTemplate(
        profile_id=profile_id,
        storage_key=storage_key,
        sha256=manifest["template_sha256"],
        manifest_json=manifest,
        version=1,
        active=False,
    )
    try:
        with session.begin_nested():
            session.add(template)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(ResumeTemplate).where(
                ResumeTemplate.profile_id == profile_id,
                ResumeTemplate.sha256 == manifest["template_sha256"],
            )
        )
        if existing:
            return existing, False
        raise
    session.add(
        AuditEvent(
            actor="owner",
            entity_id=template.id,
            event_type="resume.imported",
            payload_redacted={
                "sha256": template.sha256,
                "manifest_hash": manifest["manifest_hash"],
            },
        )
    )
    return template, True


def authorize_fields(
    session: Session, storage_root: Path, template_id: str, manifest_hash: str, field_ids: list[str]
) -> ResumeTemplate:
    template = session.scalar(
        select(ResumeTemplate).where(ResumeTemplate.id == template_id).with_for_update()
    )
    if not template:
        raise ResumeError("template_not_found")
    root = storage_root.resolve()
    master = root / template.storage_key
    if master.is_symlink() or not master.resolve().is_relative_to(root):
        raise ResumeError("invalid_storage_path")
    template.manifest_json = approve_manifest(
        master,
        template.manifest_json,
        manifest_hash=manifest_hash,
        field_ids=field_ids,
        actor="owner",
        approved_at=utcnow().isoformat(),
    )
    # Field authorization is not factual, visual, or submission approval.
    template.active = True
    session.add(
        AuditEvent(
            actor="owner",
            entity_id=template.id,
            event_type="resume.fields_authorized",
            payload_redacted={"manifest_hash": manifest_hash, "field_ids": sorted(field_ids)},
        )
    )
    return template
