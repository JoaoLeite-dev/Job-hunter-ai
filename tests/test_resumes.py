import copy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from job_hunter.infrastructure.db import AuditEvent, Profile, ResumeTemplate, VerifiedFact
from job_hunter.infrastructure.resumes import (
    ResumeError,
    approve_manifest,
    digest,
    inspect_template,
    load_package,
    resolve_source,
    store_template,
    validate_manifest,
)
from tests.resume_fake import make_resume


@pytest.fixture
def source(tmp_path):
    return make_resume(tmp_path / "incoming" / "master.docx")


def approve(source, manifest, fields, **kwargs):
    return approve_manifest(
        source,
        manifest,
        manifest_hash=kwargs.get("hash", manifest["manifest_hash"]),
        field_ids=fields,
        actor="owner",
        approved_at="2026-11-18T12:00:00Z",
    )


def test_import_preserves_every_byte_and_is_idempotent(source, tmp_path):
    before = source.read_bytes()
    key, manifest = store_template(tmp_path / "private", source)
    second_key, second = store_template(tmp_path / "private", source)
    assert second_key == key and second == manifest
    assert source.read_bytes() == before == (tmp_path / "private" / key).read_bytes()
    assert manifest["template_sha256"] == digest(before)
    assert manifest["approval"] is None
    assert manifest["validation"] == {
        "factual": "pending",
        "visual": "not_run",
        "pdf_ats": "not_run",
    }
    assert manifest["table_count"] == 1
    # Copying preserves mixed runs, tables, styles, headers and every ZIP entry exactly.
    with ZipFile(source) as original, ZipFile(tmp_path / "private" / key) as stored:
        assert original.namelist() == stored.namelist()
        assert all(original.read(name) == stored.read(name) for name in original.namelist())


def test_conservative_mapping_protects_identity_dates_numbers_and_labels(source):
    manifest = inspect_template(source)
    fields = {f["original_text"]: f for f in manifest["fields"]}
    assert fields["Developer building tested web applications with Python"]["candidate"]
    assert fields[" and accessible interfaces using React components"]["candidate"]
    assert fields["Built responsive interfaces and tested backend integrations"]["candidate"]
    assert fields["Built an inventory system for an example business"]["candidate"]
    for text in [
        "Example Person",
        "person@example.org",
        "2022 to present",
        "Engineer | Example Company",
        "Mentored 10 engineers and improved processes",
        "Project label",
        "Nested table content must stay completely protected",
    ]:
        assert not fields[text]["candidate"]
    assert len({f["field_id"] for f in manifest["fields"]}) == len(manifest["fields"])
    assert manifest == inspect_template(source)


def test_authorization_is_explicit_and_does_not_validate_facts_or_visuals(source):
    manifest = inspect_template(source)
    candidate = next(f["field_id"] for f in manifest["fields"] if f["candidate"])
    approved = approve(source, manifest, [candidate])
    assert approved["approval"]["field_ids"] == [candidate]
    assert approved["validation"]["factual"] == "pending"
    assert approved["validation"]["visual"] == "not_run"
    assert manifest["approval"] is None
    validate_manifest(source, approved)


@pytest.mark.parametrize("case", ["protected", "unknown", "empty", "duplicate", "stale"])
def test_invalid_approvals_fail_closed(source, case):
    manifest = inspect_template(source)
    candidate = next(f["field_id"] for f in manifest["fields"] if f["candidate"])
    protected = next(f["field_id"] for f in manifest["fields"] if not f["candidate"])
    selections = {
        "protected": [protected],
        "unknown": ["missing"],
        "empty": [],
        "duplicate": [candidate, candidate],
        "stale": [candidate],
    }
    with pytest.raises(ResumeError):
        approve(
            source,
            manifest,
            selections[case],
            hash="changed" if case == "stale" else manifest["manifest_hash"],
        )


def test_tampered_manifest_or_changed_master_is_rejected(source):
    manifest = inspect_template(source)
    modified = copy.deepcopy(manifest)
    modified["fields"][0]["candidate"] = True
    with pytest.raises(ResumeError, match="manifest_template_mismatch"):
        validate_manifest(source, modified)
    with source.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ResumeError, match="manifest_template_mismatch"):
        validate_manifest(source, manifest)


def test_corrupted_stored_copy_is_never_overwritten(source, tmp_path):
    root = tmp_path / "private"
    key, _ = store_template(root, source)
    target = root / key
    target.write_bytes(b"corrupted")
    with pytest.raises(ResumeError, match="stored_master_integrity_failure"):
        store_template(root, source)
    assert target.read_bytes() == b"corrupted"


def test_draft_review_artifact_is_not_silently_overwritten(source, tmp_path):
    root = tmp_path / "private"
    key, _ = store_template(root, source)
    draft = (root / key).with_name("manifest.draft.json")
    draft.write_text("{}", encoding="utf-8")
    with pytest.raises(ResumeError, match="draft_manifest_integrity_failure"):
        store_template(root, source)
    assert draft.read_text() == "{}"


@pytest.mark.parametrize(
    "name", ["../outside.docx", "sub/master.docx", r"..\outside.docx", "C:master.docx", ""]
)
def test_source_path_must_stay_in_private_folder(tmp_path, name):
    with pytest.raises(ResumeError):
        resolve_source(tmp_path, name)


@pytest.mark.parametrize("payload", ["traversal", "missing", "macro", "doctype", "doctype_utf16"])
def test_unsafe_packages_are_rejected(tmp_path, payload):
    source = make_resume(tmp_path / "malicious.docx")
    with ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    if payload == "traversal":
        parts["../outside.xml"] = b"unsafe"
    elif payload == "missing":
        del parts["_rels/.rels"]
    elif payload == "macro":
        parts["word/vbaProject.bin"] = b"unsafe"
    else:
        xml = '<!DOCTYPE doc [<!ENTITY x "unsafe">]><doc>&x;</doc>'
        parts["word/document.xml"] = xml.encode("utf-16" if payload == "doctype_utf16" else "utf-8")
    with ZipFile(source, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with pytest.raises(ResumeError):
        inspect_template(source)


def test_size_limit_and_bad_archive(source, monkeypatch):
    monkeypatch.setattr("job_hunter.infrastructure.resumes.MAX_ARCHIVE", 1)
    with pytest.raises(ResumeError, match="resume_too_large"):
        load_package(source)
    monkeypatch.setattr("job_hunter.infrastructure.resumes.MAX_ARCHIVE", 100)
    source.write_bytes(b"not a zip archive")
    with pytest.raises(ResumeError, match="unreadable_docx"):
        load_package(source)


def test_registry_api_and_no_automatic_fact_verification(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    make_resume(root / "master.docx")
    with app.extensions["session_factory"].begin() as session:
        session.add(Profile(id="real-profile", name="Local test profile"))
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token"}
    route = "/api/v1/resume-templates/import"
    body = {"source_name": "master.docx", "profile_id": "real-profile"}
    assert client.post(route, json=body).status_code == 401
    first = client.post(route, json=body, headers=headers)
    assert first.status_code == 201
    assert first.json["fields_authorized"] is False
    repeated = client.post(route, json=body, headers=headers)
    assert repeated.status_code == 200 and repeated.json["id"] == first.json["id"]
    template_id = first.json["id"]
    assert client.get("/api/v1/resume-templates/" + template_id).status_code == 401
    response = client.get("/api/v1/resume-templates/" + template_id, headers=headers)
    manifest = response.json["manifest"]
    candidates = [f["field_id"] for f in manifest["fields"] if f["candidate"]]
    approval_route = "/api/v1/resume-templates/" + template_id + "/approve-manifest"
    assert (
        client.post(
            approval_route,
            headers=headers,
            json={"manifest_hash": "stale", "field_ids": candidates},
        ).status_code
        == 409
    )
    response = client.post(
        approval_route,
        headers=headers,
        json={"manifest_hash": manifest["manifest_hash"], "field_ids": candidates[:1]},
    )
    assert response.status_code == 200 and response.json["fields_authorized"]
    assert response.json["manifest"]["validation"]["factual"] == "pending"
    with app.extensions["session_factory"]() as session:
        assert session.scalar(select(func.count()).select_from(VerifiedFact)) == 0
        assert session.scalar(select(func.count()).select_from(ResumeTemplate)) == 1
        events = session.scalars(select(AuditEvent)).all()
        assert "person@example.org" not in str([e.payload_redacted for e in events])
    assert (
        client.post(
            route, json={**body, "source_name": "../master.docx"}, headers=headers
        ).status_code
        == 400
    )


def test_cli_inspection_and_import(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    make_resume(root / "master.docx")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["resume-inspect", "--source-name", "master.docx"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["approval"] is None
    profile = runner.invoke(args=["profile-create", "--name", "Local test profile"])
    assert profile.exit_code == 0, profile.output
    imported = runner.invoke(
        args=[
            "resume-import",
            "--source-name",
            "master.docx",
            "--profile-id",
            profile.output.strip(),
        ]
    )
    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["fields_authorized"] is False
