"""Authenticated local template registry; file contents never enter audit logs."""

from pathlib import Path

import click
from flask import Blueprint, current_app, jsonify, request
from flask.cli import with_appcontext

from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.infrastructure.db import AuditEvent, Profile, ResumeTemplate
from job_hunter.infrastructure.resumes import ResumeError, resolve_source, store_template

blueprint = Blueprint("resume_templates", __name__)


def storage_root() -> Path:
    return Path(current_app.extensions["settings"].resume_storage_root)


def serialize(template: ResumeTemplate) -> dict:
    return {
        "id": template.id,
        "profile_id": template.profile_id,
        "sha256": template.sha256,
        "version": template.version,
        "fields_authorized": template.active,
        "manifest": template.manifest_json,
    }


@blueprint.post("/api/v1/resume-templates/import")
def import_resume():
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"profile_id", "source_name"}
        or not all(isinstance(v, str) and 0 < len(v) <= 250 for v in body.values())
    ):
        return jsonify(error="invalid_import_request"), 400
    try:
        source = resolve_source(storage_root(), body["source_name"])
        with current_app.extensions["session_factory"].begin() as session:
            template, created = import_template(session, storage_root(), source, body["profile_id"])
            result = serialize(template)
    except ResumeError as error:
        return jsonify(error=str(error)), 400
    return jsonify(result), 201 if created else 200


@blueprint.get("/api/v1/resume-templates/<template_id>")
def get_template(template_id):
    with current_app.extensions["session_factory"]() as session:
        template = session.get(ResumeTemplate, template_id)
        if not template:
            return jsonify(error="template_not_found"), 404
        return jsonify(serialize(template))


@blueprint.post("/api/v1/resume-templates/<template_id>/approve-manifest")
def approve_fields(template_id):
    body = request.get_json(silent=True)
    if (
        not isinstance(body, dict)
        or set(body) != {"manifest_hash", "field_ids"}
        or not isinstance(body["manifest_hash"], str)
        or not isinstance(body["field_ids"], list)
        or len(body["field_ids"]) > 1000
        or not all(isinstance(field, str) for field in body["field_ids"])
    ):
        return jsonify(error="invalid_manifest_approval"), 400
    try:
        with current_app.extensions["session_factory"].begin() as session:
            template = authorize_fields(
                session, storage_root(), template_id, body["manifest_hash"], body["field_ids"]
            )
            result = serialize(template)
    except ResumeError as error:
        status = 404 if str(error) == "template_not_found" else 409
        return jsonify(error=str(error)), status
    return jsonify(result)


@click.command("profile-create")
@click.option("--name", required=True, help="Name of the local profile; no facts are verified.")
@with_appcontext
def profile_create(name):
    if not name.strip() or len(name) > 200:
        raise click.ClickException("Invalid profile name")
    with current_app.extensions["session_factory"].begin() as session:
        profile = Profile(name=name.strip())
        session.add(profile)
        session.flush()
        session.add(
            AuditEvent(
                actor="owner",
                entity_id=profile.id,
                event_type="profile.created",
                payload_redacted={},
            )
        )
        click.echo(profile.id)


@click.command("resume-inspect")
@click.option("--source-name", required=True, help="DOCX filename inside RESUME_STORAGE_ROOT.")
@with_appcontext
def resume_inspect(source_name):
    import json

    try:
        source = resolve_source(storage_root(), source_name)
        key, manifest = store_template(storage_root(), source)
    except ResumeError as error:
        raise click.ClickException(str(error)) from None
    click.echo(
        json.dumps(
            {
                "template_sha256": manifest["template_sha256"],
                "manifest_hash": manifest["manifest_hash"],
                "manifest_path": str(Path(key).parent / "manifest.draft.json"),
                "candidate_field_ids": [
                    f["field_id"] for f in manifest["fields"] if f["candidate"]
                ],
                "approval": None,
                "visual_validation": "not_run",
            }
        )
    )


@click.command("resume-import")
@click.option("--source-name", required=True)
@click.option("--profile-id", required=True)
@with_appcontext
def resume_import(source_name, profile_id):
    import json

    try:
        source = resolve_source(storage_root(), source_name)
        with current_app.extensions["session_factory"].begin() as session:
            template, created = import_template(session, storage_root(), source, profile_id)
            result = {
                "id": template.id,
                "created": created,
                "manifest_hash": template.manifest_json["manifest_hash"],
                "fields_authorized": template.active,
            }
    except ResumeError as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(result))
