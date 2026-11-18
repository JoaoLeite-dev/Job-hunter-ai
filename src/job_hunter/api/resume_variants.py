"""Authenticated draft operations; clients cannot supply validation results."""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from job_hunter.application.resume_validation import (
    validate_variant,
    validation_complete,
    verify_pdf,
)
from job_hunter.application.resume_variants import (
    confirm_template_facts,
    confirm_wording,
    create_variant,
    verify_current_variant,
)
from job_hunter.infrastructure.db import ResumeVariant
from job_hunter.infrastructure.resumes import ResumeError

blueprint = Blueprint("resume_variants", __name__)


def root() -> Path:
    return Path(current_app.extensions["settings"].resume_storage_root)


def error_response(error):
    code = str(error)
    status = (
        404
        if code in {"template_not_found", "job_not_found", "variant_not_found", "pdf_not_available"}
        else 409
    )
    return jsonify(error=code), status


def serialize(variant):
    return {
        "id": variant.id,
        "job_id": variant.job_id,
        "template_id": variant.template_id,
        "sha256_docx": variant.sha256_docx,
        "state": variant.state,
        "validation": variant.validation_json,
        "can_approve_application": False,
        "pdf_available": bool(variant.pdf_key and variant.sha256_pdf),
        "sha256_pdf": variant.sha256_pdf,
        "validation_complete": validation_complete(variant),
    }


@blueprint.post("/api/v1/resume-templates/<template_id>/wording-facts")
def wording_fact(template_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"manifest_hash", "field_id", "claim", "confirmed"}
        or body["confirmed"] is not True
        or not all(isinstance(body[k], str) for k in ["manifest_hash", "field_id", "claim"])
    ):
        return jsonify(error="explicit_wording_confirmation_required"), 400
    try:
        with current_app.extensions["session_factory"].begin() as session:
            fact = confirm_wording(
                session, root(), template_id, body["manifest_hash"], body["field_id"], body["claim"]
            )
            result = {"id": fact.id, "version": fact.version, "category": fact.category}
    except ResumeError as error:
        return error_response(error)
    return jsonify(result), 200


@blueprint.post("/api/v1/jobs/<job_id>/resume-variants")
def generate_variant(job_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"template_id", "edits"}
        or not isinstance(body["template_id"], str)
        or not isinstance(body["edits"], list)
    ):
        return jsonify(error="invalid_variant_request"), 400
    try:
        with current_app.extensions["session_factory"].begin() as session:
            variant, created = create_variant(
                session,
                root(),
                job_id,
                body["template_id"],
                body["edits"],
                threshold=current_app.extensions["settings"].match_prepare_threshold,
            )
            result = serialize(variant)
    except ResumeError as error:
        return error_response(error)
    return jsonify(result), 201 if created else 200


@blueprint.get("/api/v1/resume-variants/<variant_id>")
def get_variant(variant_id):
    try:
        with current_app.extensions["session_factory"]() as session:
            variant = session.get(ResumeVariant, variant_id)
            if not variant:
                return jsonify(error="variant_not_found"), 404
            verify_current_variant(session, root(), variant)
            if variant.pdf_key:
                verify_pdf(root(), variant)
            return jsonify(serialize(variant))
    except ResumeError as error:
        return error_response(error)


@blueprint.post("/api/v1/resume-templates/<template_id>/confirm-facts")
def confirm_cv_facts(template_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"manifest_hash", "confirmed"}
        or body["confirmed"] is not True
        or not isinstance(body["manifest_hash"], str)
    ):
        return jsonify(error="explicit_fact_confirmation_required"), 400
    try:
        with current_app.extensions["session_factory"].begin() as session:
            result = confirm_template_facts(session, root(), template_id, body["manifest_hash"])
    except ResumeError as error:
        return error_response(error)
    return jsonify(result)


@blueprint.post("/api/v1/resume-variants/<variant_id>/validate")
def validate_document(variant_id):
    if request.get_data() and request.get_json(silent=True) != {}:
        return jsonify(error="validation_results_cannot_be_supplied"), 400
    if not current_app.extensions["settings"].resume_render_enabled:
        return jsonify(error="document_renderer_disabled"), 409
    try:
        renderer = current_app.extensions["document_renderer_factory"]()
        with current_app.extensions["session_factory"].begin() as session:
            variant = validate_variant(session, root(), variant_id, renderer)
            result = serialize(variant)
    except ResumeError as error:
        return error_response(error)
    return jsonify(result)


@blueprint.get("/api/v1/resume-variants/<variant_id>/pdf")
def download_pdf(variant_id):
    try:
        with current_app.extensions["session_factory"]() as session:
            variant = session.get(ResumeVariant, variant_id)
            if not variant:
                return jsonify(error="variant_not_found"), 404
            verify_current_variant(session, root(), variant)
            path = verify_pdf(root(), variant)
            response = send_file(
                path,
                mimetype="application/pdf",
                as_attachment=True,
                download_name="resume.pdf",
                conditional=False,
                max_age=0,
            )
            response.headers["Cache-Control"] = "private, no-store"
            return response
    except ResumeError as error:
        return error_response(error)
