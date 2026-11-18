"""Server-side wording confirmation and draft variant creation. No email or external AI calls."""

from datetime import UTC, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.infrastructure.db import (
    AuditEvent,
    Job,
    Match,
    ResumeTemplate,
    ResumeVariant,
    VerifiedFact,
    utcnow,
)
from job_hunter.infrastructure.resume_editor import (
    WordingFact,
    build_docx,
    validate_edits,
    validate_wording,
    wording_source,
)
from job_hunter.infrastructure.resumes import (
    ResumeError,
    canonical_json,
    digest,
    fold,
    validate_manifest,
)


def master_path(root: Path, template: ResumeTemplate) -> Path:
    root = root.resolve()
    path = root / template.storage_key
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ResumeError("invalid_storage_path")
    return path


def confirm_wording(
    session: Session, root: Path, template_id: str, manifest_hash: str, field_id: str, claim: str
) -> VerifiedFact:
    template = session.scalar(
        select(ResumeTemplate).where(ResumeTemplate.id == template_id).with_for_update()
    )
    if not template:
        raise ResumeError("template_not_found")
    if manifest_hash != template.manifest_json["manifest_hash"]:
        raise ResumeError("manifest_hash_mismatch")
    validate_wording(master_path(root, template), template.manifest_json, field_id, claim)
    source = wording_source(template.manifest_json, field_id)
    fact = session.scalar(
        select(VerifiedFact).where(
            VerifiedFact.profile_id == template.profile_id,
            VerifiedFact.category == "resume_wording",
            VerifiedFact.claim == claim,
            VerifiedFact.evidence_source == source,
            VerifiedFact.verified_at.is_not(None),
        )
    )
    if fact:
        return fact
    fact = VerifiedFact(
        profile_id=template.profile_id,
        category="resume_wording",
        claim=claim,
        evidence_source=source,
        verified_at=utcnow(),
        version=1,
    )
    session.add(fact)
    session.flush()
    session.add(
        AuditEvent(
            actor="owner",
            entity_id=fact.id,
            event_type="resume.wording_confirmed",
            payload_redacted={
                "template_id": template_id,
                "field_id": field_id,
                "claim_sha256": digest(claim.encode("utf-8")),
            },
        )
    )
    return fact


def verify_artifact(root: Path, variant: ResumeVariant) -> Path:
    root = root.resolve()
    path = root / variant.docx_key
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ResumeError("invalid_storage_path")
    if not path.is_file() or digest(path.read_bytes()) != variant.sha256_docx:
        raise ResumeError("variant_integrity_failure")
    return path


def create_variant(
    session: Session, root: Path, job_id: str, template_id: str, edits: list, *, threshold: int = 75
) -> tuple[ResumeVariant, bool]:
    template = session.scalar(
        select(ResumeTemplate).where(ResumeTemplate.id == template_id).with_for_update()
    )
    if not template:
        raise ResumeError("template_not_found")
    if not template.active:
        raise ResumeError("manifest_not_authorized")
    job = session.get(Job, job_id)
    if not job:
        raise ResumeError("job_not_found")
    if job.status != "active" or not job.last_verified_at:
        raise ResumeError("job_requires_revalidation")
    verified_at = job.last_verified_at
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    if verified_at < utcnow() - timedelta(hours=24) or verified_at > utcnow() + timedelta(
        minutes=5
    ):
        raise ResumeError("job_requires_revalidation")
    match = session.scalar(
        select(Match).where(Match.job_id == job_id, Match.profile_id == template.profile_id)
    )
    if not match or match.hard_gate or match.score < threshold:
        raise ResumeError("job_match_not_eligible")
    facts = [
        WordingFact(
            f.id, f.category, f.claim, f.evidence_source, f.verified_at is not None, f.version
        )
        for f in session.scalars(
            select(VerifiedFact).where(VerifiedFact.profile_id == template.profile_id)
        )
    ]
    master = master_path(root, template)
    docx, report = build_docx(master, template.manifest_json, edits, facts)
    existing = session.scalar(
        select(ResumeVariant).where(
            ResumeVariant.job_id == job_id,
            ResumeVariant.template_id == template_id,
            ResumeVariant.request_hash == report["plan_hash"],
        )
    )
    if existing:
        verify_artifact(root, existing)
        return existing, False
    directory = root.resolve() / "variants" / report["plan_hash"]
    if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
        raise ResumeError("invalid_storage_path")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "resume.docx"
    if target.is_symlink():
        raise ResumeError("invalid_storage_path")
    try:
        with target.open("xb") as handle:
            handle.write(docx)
    except FileExistsError:
        if digest(target.read_bytes()) != digest(docx):
            raise ResumeError("variant_integrity_failure") from None
    variant = ResumeVariant(
        job_id=job_id,
        template_id=template_id,
        request_hash=report["plan_hash"],
        docx_key=target.relative_to(root.resolve()).as_posix(),
        sha256_docx=digest(docx),
        edits_json=report["edits"],
        evidence_json=report["evidence"],
        validation_json={
            key: report[key] for key in ["factual", "structural", "docx_ats", "visual", "pdf_ats"]
        },
        state="validation_pending",
    )
    session.add(variant)
    session.flush()
    session.add(
        AuditEvent(
            actor="owner",
            entity_id=variant.id,
            event_type="resume.variant_drafted",
            payload_redacted={
                "job_id": job_id,
                "template_id": template_id,
                "sha256_docx": variant.sha256_docx,
                "state": variant.state,
            },
        )
    )
    return variant, True


def confirm_template_facts(
    session: Session, root: Path, template_id: str, manifest_hash: str
) -> dict:
    template = session.scalar(
        select(ResumeTemplate).where(ResumeTemplate.id == template_id).with_for_update()
    )
    if not template:
        raise ResumeError("template_not_found")
    manifest = template.manifest_json
    if manifest_hash != manifest["manifest_hash"]:
        raise ResumeError("manifest_hash_mismatch")
    validate_manifest(master_path(root, template), manifest)
    approved_ids = set((manifest.get("approval") or {}).get("field_ids", []))
    confirmations = []
    groups = {}
    for field in manifest["fields"]:
        groups.setdefault(field["paragraph_index"], []).append(field)
        style = fold(field["style"])
        if style in {"title", "contact"} or style.startswith("heading"):
            continue
        claim = field["original_text"].strip()
        if claim:
            category = "resume_wording" if field["field_id"] in approved_ids else "resume_text"
            confirmations.append(
                (category, field["original_text"], wording_source(manifest, field["field_id"]))
            )
    technical_section = False
    for fields in groups.values():
        text = "".join(f["original_text"] for f in fields)
        if fold(fields[0]["style"]).startswith("heading"):
            technical_section = fold(text) == "competencias tecnicas"
            continue
        explicit_stack = fold(fields[0]["original_text"]).startswith("tecnologias")
        if len(fields) > 1 and (technical_section or explicit_stack):
            data_field = fields[-1]
            for skill in data_field["original_text"].split(","):
                if skill.strip():
                    confirmations.append(
                        (
                            "technical",
                            skill.strip(),
                            wording_source(manifest, data_field["field_id"]),
                        )
                    )
    created = 0
    for category, claim, source in confirmations:
        fact = session.scalar(
            select(VerifiedFact).where(
                VerifiedFact.profile_id == template.profile_id,
                VerifiedFact.category == category,
                VerifiedFact.claim == claim,
                VerifiedFact.evidence_source == source,
            )
        )
        if fact is None:
            session.add(
                VerifiedFact(
                    profile_id=template.profile_id,
                    category=category,
                    claim=claim,
                    evidence_source=source,
                    verified_at=utcnow(),
                    version=1,
                )
            )
            created += 1
        elif fact.verified_at is None:
            fact.verified_at = utcnow()
            fact.version += 1
        session.flush()
    session.add(
        AuditEvent(
            actor="owner",
            entity_id=template_id,
            event_type="resume.facts_confirmed",
            payload_redacted={
                "manifest_hash": manifest_hash,
                "created": created,
                "source": "owner_confirmation",
            },
        )
    )
    return {
        "created": created,
        "template_id": template_id,
        "manifest_hash": manifest_hash,
        "confirmation": "owner",
    }


def verify_current_variant(session: Session, root: Path, variant: ResumeVariant) -> Path:
    path = verify_artifact(root, variant)
    template = session.get(ResumeTemplate, variant.template_id)
    if not template or not template.active:
        raise ResumeError("manifest_not_authorized")
    facts = [
        WordingFact(
            f.id, f.category, f.claim, f.evidence_source, f.verified_at is not None, f.version
        )
        for f in session.scalars(
            select(VerifiedFact).where(VerifiedFact.profile_id == template.profile_id)
        )
    ]
    edits, evidence = validate_edits(
        master_path(root, template), template.manifest_json, variant.edits_json, facts
    )
    current_hash = digest(
        canonical_json(
            {
                "manifest_hash": template.manifest_json["manifest_hash"],
                "approval": template.manifest_json["approval"],
                "edits": edits,
                "evidence": evidence,
            }
        )
    )
    if evidence != variant.evidence_json or current_hash != variant.request_hash:
        raise ResumeError("variant_evidence_changed")
    return path
