"""Validate real rendered artifacts; no client-supplied check can release a draft."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_hunter.application.resume_variants import master_path, verify_current_variant
from job_hunter.infrastructure.db import AuditEvent, ResumeTemplate, ResumeVariant
from job_hunter.infrastructure.document_renderer import RenderError
from job_hunter.infrastructure.pdf_validation import compare_pdfs
from job_hunter.infrastructure.resume_editor import validate_structure
from job_hunter.infrastructure.resumes import ResumeError, digest

CHECKS = ("factual", "structural", "docx_ats", "visual", "pdf_ats")


def validation_complete(variant: ResumeVariant) -> bool:
    return (
        variant.state == "validated"
        and bool(variant.pdf_key and variant.sha256_pdf)
        and all(
            variant.validation_json.get(check, {}).get("status") == "passed" for check in CHECKS
        )
    )


def verify_pdf(root: Path, variant: ResumeVariant) -> Path:
    if not variant.pdf_key or not variant.sha256_pdf:
        raise ResumeError("pdf_not_available")
    root = root.resolve()
    path = root / variant.pdf_key
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ResumeError("invalid_storage_path")
    if not path.is_file() or digest(path.read_bytes()) != variant.sha256_pdf:
        raise ResumeError("pdf_integrity_failure")
    return path


def validate_variant(session: Session, root: Path, variant_id: str, renderer) -> ResumeVariant:
    variant = session.scalar(
        select(ResumeVariant).where(ResumeVariant.id == variant_id).with_for_update()
    )
    if not variant:
        raise ResumeError("variant_not_found")
    docx = verify_current_variant(session, root, variant)
    if validation_complete(variant):
        verify_pdf(root, variant)
        return variant
    template = session.get(ResumeTemplate, variant.template_id)
    master = master_path(root, template)
    validate_structure(master, docx.read_bytes(), template.manifest_json, variant.edits_json)
    report = {**variant.validation_json}
    variant.pdf_key = None
    variant.sha256_pdf = None
    try:
        engine = renderer.version
        original_pdf = renderer.render(master)
        output_pdf = renderer.render(docx)
        # Recheck both DOCX files after the external converter finishes.
        verify_current_variant(session, root, variant)
        validate_structure(master, docx.read_bytes(), template.manifest_json, variant.edits_json)
        report.update(
            compare_pdfs(original_pdf, output_pdf, template.manifest_json, variant.edits_json)
        )
        pdf_hash = digest(output_pdf)
        target = docx.with_name(pdf_hash + ".pdf")
        if target.is_symlink():
            raise ResumeError("invalid_storage_path")
        try:
            with target.open("xb") as handle:
                handle.write(output_pdf)
        except FileExistsError:
            if digest(target.read_bytes()) != pdf_hash:
                raise ResumeError("pdf_integrity_failure") from None
        variant.pdf_key = target.relative_to(root.resolve()).as_posix()
        variant.sha256_pdf = pdf_hash
        report["render"] = {
            "engine": engine,
            "baseline_pdf_sha256": digest(original_pdf),
            "variant_pdf_sha256": pdf_hash,
            "validator_version": 1,
        }
    except RenderError as error:
        report["visual"] = {"status": "failed", "code": str(error)}
        report["pdf_ats"] = {"status": "not_run"}
    variant.validation_json = report
    variant.state = (
        "validated"
        if all(report.get(c, {}).get("status") == "passed" for c in CHECKS) and variant.pdf_key
        else "validation_failed"
    )
    session.add(
        AuditEvent(
            actor="validator",
            entity_id=variant.id,
            event_type="resume.validated",
            payload_redacted={
                "state": variant.state,
                "sha256_pdf": variant.sha256_pdf,
                "checks": {c: report.get(c, {}).get("status") for c in CHECKS},
            },
        )
    )
    session.flush()
    return variant
