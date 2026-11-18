"""Authenticated draft operations; clients cannot supply validation results."""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

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
    status = 404 if code in {"template_not_found", "job_not_found"} else 409
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
        "pdf_available": False,
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
