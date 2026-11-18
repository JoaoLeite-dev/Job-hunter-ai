import copy
import io
from datetime import timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from job_hunter.application.resume_variants import (
    confirm_template_facts,
    confirm_wording,
    create_variant,
)
from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.infrastructure.db import (
    AuditEvent,
    Job,
    Match,
    Profile,
    ResumeVariant,
    VerifiedFact,
    utcnow,
)
from job_hunter.infrastructure.resume_editor import (
    WordingFact,
    build_docx,
    validate_structure,
    wording_source,
)
from job_hunter.infrastructure.resumes import (
    ResumeError,
    approve_manifest,
    inspect_template,
)
from tests.resume_fake import make_resume

NEW_TEXT = "Built tested web applications with Python"


@pytest.fixture
def editor_case(tmp_path):
    master = make_resume(tmp_path / "master.docx")
    manifest = inspect_template(master)
    field = next(f for f in manifest["fields"] if f["candidate"])
    manifest = approve_manifest(
        master,
        manifest,
        manifest_hash=manifest["manifest_hash"],
        field_ids=[field["field_id"]],
        actor="owner",
        approved_at="2026-11-18T12:00:00Z",
    )
    edit = {
        "field_id": field["field_id"],
        "original_text": field["original_text"],
        "proposed_text": NEW_TEXT,
        "supporting_fact_ids": ["fact-1"],
    }
    fact = WordingFact(
        "fact-1", "resume_wording", NEW_TEXT, wording_source(manifest, field["field_id"]), True, 1
    )
    return master, manifest, field, edit, fact


def test_editor_changes_only_authorized_xml_text(editor_case):
    master, manifest, field, edit, fact = editor_case
    before = master.read_bytes()
    output, report = build_docx(master, manifest, [edit], [fact])
    assert master.read_bytes() == before
    assert report["state"] == "validation_pending"
    assert report["factual"]["status"] == report["structural"]["status"] == "passed"
    assert report["visual"]["status"] == report["pdf_ats"]["status"] == "not_run"
    with ZipFile(master) as original, ZipFile(io.BytesIO(output)) as variant:
        assert original.namelist() == variant.namelist()
        for name in original.namelist():
            expected = original.read(name)
            if name == "word/document.xml":
                expected = expected.replace(field["original_text"].encode(), NEW_TEXT.encode(), 1)
            assert variant.read(name) == expected
    assert output == build_docx(master, manifest, [edit], [fact])[0]


def test_xml_injection_is_written_as_literal_text(editor_case):
    master, manifest, _, edit, fact = editor_case
    text = "Built APIs & tested <interfaces>"
    edit["proposed_text"] = text
    fact = WordingFact(fact.id, fact.category, text, fact.evidence_source, True, 1)
    output, _ = build_docx(master, manifest, [edit], [fact])
    with ZipFile(io.BytesIO(output)) as variant:
        xml = variant.read("word/document.xml")
        assert b"&amp;" in xml and b"&lt;interfaces&gt;" in xml
        assert b"<interfaces>" not in xml


@pytest.mark.parametrize(
    "case",
    [
        "no_approval",
        "protected",
        "stale_original",
        "missing_fact",
        "unverified",
        "wrong_field_fact",
        "unrelated_claim",
        "wrong_category",
        "too_long",
        "duplicate",
        "extra_schema",
        "numbers",
        "controls",
        "email",
        "empty_plan",
        "noop",
    ],
)
def test_editor_rejects_unsafe_edits(editor_case, case):
    master, manifest, field, edit, fact = editor_case
    facts = [fact]
    edits = [edit]
    if case == "no_approval":
        manifest["approval"] = None
    elif case == "protected":
        edit["field_id"] = next(f["field_id"] for f in manifest["fields"] if not f["candidate"])
    elif case == "stale_original":
        edit["original_text"] = "different"
    elif case == "missing_fact":
        facts = []
    elif case == "unverified":
        facts = [WordingFact(fact.id, fact.category, fact.claim, fact.evidence_source, False, 1)]
    elif case == "wrong_field_fact":
        facts = [WordingFact(fact.id, fact.category, fact.claim, "another-field", True, 1)]
    elif case == "unrelated_claim":
        facts = [WordingFact(fact.id, fact.category, "Terraform", fact.evidence_source, True, 1)]
    elif case == "wrong_category":
        facts = [WordingFact(fact.id, "technical", fact.claim, fact.evidence_source, True, 1)]
    elif case == "too_long":
        edit["proposed_text"] = "X" * (field["max_characters"] + 1)
    elif case == "duplicate":
        edits.append(copy.deepcopy(edit))
    elif case == "extra_schema":
        edit["visual_passed"] = True
    elif case == "numbers":
        edit["proposed_text"] = "Built applications for 100 engineers"
    elif case == "controls":
        edit["proposed_text"] = "Built\napplications"
    elif case == "email":
        edit["proposed_text"] = "Contact new@example.org"
    elif case == "empty_plan":
        edits = []
    elif case == "noop":
        edit["proposed_text"] = edit["original_text"]
    with pytest.raises(ResumeError):
        build_docx(master, manifest, edits, facts)


@pytest.mark.parametrize("part", ["word/styles.xml", "word/header1.xml", "word/document.xml"])
def test_structural_validation_catches_protected_changes(editor_case, part):
    master, manifest, _, edit, fact = editor_case
    output, _ = build_docx(master, manifest, [edit], [fact])
    altered = io.BytesIO()
    with ZipFile(io.BytesIO(output)) as source, ZipFile(altered, "w") as destination:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == part:
                data = (
                    data.replace(b"Protected header", b"Changed header")
                    if "header" in part
                    else data + b" "
                )
            destination.writestr(info, data)
    with pytest.raises(ResumeError, match="protected_document_content_changed"):
        validate_structure(master, altered.getvalue(), manifest, [edit])


@pytest.fixture
def variant_case(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    source = make_resume(root / "master.docx")
    with app.extensions["session_factory"].begin() as session:
        session.add(Profile(id="profile", name="Synthetic profile"))
        session.flush()
        template, _ = import_template(session, root, source, "profile")
        field = next(f for f in template.manifest_json["fields"] if f["candidate"])
        authorize_fields(
            session, root, template.id, template.manifest_json["manifest_hash"], [field["field_id"]]
        )
        session.add(
            Job(
                id="job",
                source_id="fixture",
                external_id="one",
                canonical_url="https://example.org/jobs/one",
                company="Synthetic",
                title="Full Stack",
                description="Synthetic job",
                status="active",
                last_verified_at=utcnow(),
                data={},
            )
        )
        session.flush()
        session.add(
            Match(job_id="job", profile_id="profile", score=90, hard_gate=False, evidence={})
        )
        values = {
            "template_id": template.id,
            "manifest_hash": template.manifest_json["manifest_hash"],
            "field_id": field["field_id"],
            "original_text": field["original_text"],
            "root": root,
        }
    return values


def plan(case, fact_id):
    return [
        {
            "field_id": case["field_id"],
            "original_text": case["original_text"],
            "proposed_text": NEW_TEXT,
            "supporting_fact_ids": [fact_id],
        }
    ]


def test_fact_confirmation_is_explicit_version_bound_and_idempotent(app, variant_case):
    case = variant_case
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token"}
    path = f"/api/v1/resume-templates/{case['template_id']}/confirm-facts"
    assert (
        client.post(
            path, json={"manifest_hash": case["manifest_hash"], "confirmed": True}
        ).status_code
        == 401
    )
    assert (
        client.post(
            path, headers=headers, json={"manifest_hash": case["manifest_hash"], "confirmed": False}
        ).status_code
        == 400
    )
    first = client.post(
        path, headers=headers, json={"manifest_hash": case["manifest_hash"], "confirmed": True}
    )
    assert first.status_code == 200 and first.json["created"] > 0
    replay = client.post(
        path, headers=headers, json={"manifest_hash": case["manifest_hash"], "confirmed": True}
    )
    assert replay.json["created"] == 0
    with app.extensions["session_factory"]() as session:
        assert not session.scalar(select(VerifiedFact).where(VerifiedFact.claim == "Terraform"))
        audit = session.scalars(select(AuditEvent)).all()
        assert "Example Person" not in str([e.payload_redacted for e in audit])


def test_api_draft_is_private_idempotent_and_never_ready(app, variant_case):
    case = variant_case
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token"}
    fact_path = f"/api/v1/resume-templates/{case['template_id']}/wording-facts"
    body = {
        "manifest_hash": case["manifest_hash"],
        "field_id": case["field_id"],
        "claim": NEW_TEXT,
        "confirmed": True,
    }
    assert client.post(fact_path, json=body).status_code == 401
    bad = {**body, "confirmed": "true"}
    assert client.post(fact_path, headers=headers, json=bad).status_code == 400
    fact = client.post(fact_path, headers=headers, json=body)
    assert fact.status_code == 200
    assert client.post(fact_path, headers=headers, json=body).json == fact.json
    path = "/api/v1/jobs/job/resume-variants"
    request = {"template_id": case["template_id"], "edits": plan(case, fact.json["id"])}
    assert client.post(path, json=request).status_code == 401
    assert (
        client.post(path, headers=headers, json={**request, "visual_passed": True}).status_code
        == 400
    )
    first = client.post(path, headers=headers, json=request)
    assert first.status_code == 201, first.json
    assert first.json["state"] == "validation_pending"
    assert first.json["can_approve_application"] is False
    assert first.json["pdf_available"] is False
    repeated = client.post(path, headers=headers, json=request)
    assert repeated.status_code == 200 and repeated.json["id"] == first.json["id"]
    get_path = "/api/v1/resume-variants/" + first.json["id"]
    assert client.get(get_path).status_code == 401
    assert client.get(get_path, headers=headers).status_code == 200
    with app.extensions["session_factory"].begin() as session:
        assert session.scalar(select(func.count()).select_from(ResumeVariant)) == 1
        variant = session.get(ResumeVariant, first.json["id"])
        (case["root"] / variant.docx_key).write_bytes(b"corrupted")
    assert client.get(get_path, headers=headers).status_code == 409


@pytest.mark.parametrize(
    "gate", ["expired", "stale", "hard_gate", "low_score", "foreign_fact", "revoked"]
)
def test_generation_gates(app, variant_case, gate):
    case = variant_case
    with app.extensions["session_factory"].begin() as session:
        fact = confirm_wording(
            session,
            case["root"],
            case["template_id"],
            case["manifest_hash"],
            case["field_id"],
            NEW_TEXT,
        )
        fact_id = fact.id
        if gate == "expired":
            session.get(Job, "job").status = "expired"
        elif gate == "stale":
            session.get(Job, "job").last_verified_at = utcnow() - timedelta(days=2)
        elif gate == "hard_gate":
            session.scalar(select(Match)).hard_gate = True
        elif gate == "low_score":
            session.scalar(select(Match)).score = 30
        elif gate == "foreign_fact":
            session.add(Profile(id="other", name="Other profile"))
            session.flush()
            fact.profile_id = "other"
        elif gate == "revoked":
            fact.verified_at = None
    with pytest.raises(ResumeError), app.extensions["session_factory"].begin() as session:
        create_variant(session, case["root"], "job", case["template_id"], plan(case, fact_id))
    with app.extensions["session_factory"]() as session:
        assert session.scalar(select(func.count()).select_from(ResumeVariant)) == 0
    assert not list(case["root"].glob("variants/*/resume.docx"))


def test_variant_revalidation_rejects_revoked_or_changed_evidence(app, variant_case):
    case = variant_case
    with app.extensions["session_factory"].begin() as session:
        fact = confirm_wording(
            session,
            case["root"],
            case["template_id"],
            case["manifest_hash"],
            case["field_id"],
            NEW_TEXT,
        )
        fact_id = fact.id
        variant, _ = create_variant(
            session, case["root"], "job", case["template_id"], plan(case, fact_id)
        )
        variant_id = variant.id
    client = app.test_client()
    path = "/api/v1/resume-variants/" + variant_id
    headers = {"Authorization": "Bearer test-token"}
    assert client.get(path, headers=headers).status_code == 200
    with app.extensions["session_factory"].begin() as session:
        session.get(VerifiedFact, fact_id).version += 1
    assert client.get(path, headers=headers).json["error"] == "variant_evidence_changed"
    with app.extensions["session_factory"].begin() as session:
        fact = session.get(VerifiedFact, fact_id)
        fact.version -= 1
        fact.verified_at = None
    assert client.get(path, headers=headers).status_code == 409


def test_template_confirmation_extracts_only_explicit_skills(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    source = make_resume(root / "skills.docx")
    with ZipFile(source) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    extra = (
        b'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        b"<w:r><w:t>Competencias tecnicas</w:t></w:r></w:p>"
        b"<w:p><w:r><w:t>Frontend</w:t></w:r>"
        b"<w:r><w:t>React, TypeScript</w:t></w:r></w:p>"
    )
    with ZipFile(source, "w") as archive:
        for info, data in entries:
            if info.filename == "word/document.xml":
                data = data.replace(b"<w:sectPr>", extra + b"<w:sectPr>")
            archive.writestr(info, data)
    with app.extensions["session_factory"].begin() as session:
        session.add(Profile(id="skills-profile", name="Synthetic skills profile"))
        session.flush()
        template, _ = import_template(session, root, source, "skills-profile")
        confirm_template_facts(session, root, template.id, template.manifest_json["manifest_hash"])
        technical = set(
            session.scalars(select(VerifiedFact.claim).where(VerifiedFact.category == "technical"))
        )
        assert technical == {"React", "TypeScript"}
        assert "Terraform" not in technical and "Python" not in technical
