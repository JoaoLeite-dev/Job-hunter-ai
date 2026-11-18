"""PDF checks use synthetic documents only; no personal CV is versioned."""

import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pymupdf
import pytest

from job_hunter import create_app
from job_hunter.application.resume_validation import validate_variant, validation_complete
from job_hunter.application.resume_variants import confirm_wording, create_variant
from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.infrastructure.db import Job, Match, Profile, ResumeVariant, utcnow
from job_hunter.infrastructure.document_renderer import (
    LibreOfficeRenderer,
    RenderError,
    check_renderable,
)
from job_hunter.infrastructure.pdf_validation import compare_pdfs
from job_hunter.infrastructure.resumes import W, digest, load_package
from tests.resume_fake import make_resume

FIELDS = [
    ("name", "Example Person", (50, 50)),
    ("summary", "Built Python web applications", (50, 100)),
    ("contact", "person@example.org", (50, 150)),
    ("dates", "2022 to present", (50, 180)),
]
MANIFEST = {"fields": [{"field_id": key, "original_text": text} for key, text, _ in FIELDS]}
EDITS = [{"field_id": "summary", "proposed_text": "Built Python apps"}]


def pdf_scene(
    *,
    edits=False,
    move=False,
    extra_page=False,
    omit=False,
    reverse=False,
    shape=False,
    image_shift=0,
    add_image=False,
    expand=False,
):
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    values = list(reversed(FIELDS)) if reverse else FIELDS
    for key, text, position in values:
        if omit and key == "contact":
            continue
        if edits and key == "summary":
            text = "Built Python apps"
        if expand and key == "summary":
            text = "Built Python apps and many wider complex applications"
        if move and key == "dates":
            position = (position[0], position[1] + 12)
        page.insert_text(position, text, fontsize=10)
    if shape:
        page.draw_rect(pymupdf.Rect(50, 220, 200, 240))
    if add_image:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        pixmap.clear_with(240)
        page.insert_image(pymupdf.Rect(400 + image_shift, 50, 420 + image_shift, 70), pixmap=pixmap)
    if extra_page:
        document.new_page()
    result = document.tobytes()
    document.close()
    return result


def test_pdf_text_and_anchors_pass_for_bounded_edit():
    report = compare_pdfs(pdf_scene(), pdf_scene(edits=True), MANIFEST, EDITS)
    assert report["visual"]["status"] == report["pdf_ats"]["status"] == "passed"
    assert report["visual"]["protected_anchors_checked"] == 3


@pytest.mark.parametrize(
    "change,code",
    [
        ("move", "protected_text_moved"),
        ("extra_page", "page_count_changed"),
        ("shape", "vector_layout_changed"),
        ("expand", "edited_text_exceeds_original_bounds"),
    ],
)
def test_layout_changes_fail_closed(change, code):
    edits = (
        EDITS
        if change != "expand"
        else [
            {
                "field_id": "summary",
                "proposed_text": "Built Python apps and many wider complex applications",
            }
        ]
    )
    report = compare_pdfs(pdf_scene(), pdf_scene(**{change: True}), MANIFEST, edits)
    assert report["visual"]["status"] == "failed"
    assert code in report["visual"]["issues"]


def test_missing_text_and_changed_reading_order_are_detected():
    missing = compare_pdfs(pdf_scene(), pdf_scene(omit=True), MANIFEST, [])
    assert missing["pdf_ats"]["missing_field_ids"] == ["contact"]
    reordered = compare_pdfs(pdf_scene(), pdf_scene(reverse=True), MANIFEST, [])
    assert reordered["pdf_ats"]["status"] == "failed"
    assert reordered["pdf_ats"]["out_of_order_field_ids"]


def test_image_layout_is_preserved_or_blocked():
    baseline = pdf_scene(add_image=True)
    assert compare_pdfs(baseline, baseline, MANIFEST, [])["visual"]["status"] == "passed"
    shifted = compare_pdfs(baseline, pdf_scene(add_image=True, image_shift=10), MANIFEST, [])
    assert "image_layout_changed" in shifted["visual"]["issues"]


def test_invalid_and_blank_pdfs_are_rejected():
    with pytest.raises(RenderError, match="invalid_rendered_pdf"):
        compare_pdfs(b"not a pdf", pdf_scene(), MANIFEST, [])
    blank = pymupdf.open()
    blank.new_page()
    with pytest.raises(RenderError, match="pdf_text_missing"):
        compare_pdfs(blank.tobytes(), pdf_scene(), MANIFEST, [])
    blank.close()


@pytest.mark.parametrize("kind", ["external_image", "unsafe_link", "dde"])
def test_renderer_blocks_external_resources(tmp_path, kind):
    source = make_resume(tmp_path / "master.docx")
    with ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if kind == "dde":
        entries["word/document.xml"] = entries["word/document.xml"].replace(
            b"</w:body>",
            b"<w:p><w:r><w:instrText>DDEAUTO malicious</w:instrText></w:r></w:p></w:body>",
        )
    else:
        relation_type = "image" if kind == "external_image" else "hyperlink"
        target = (
            "https://example.org/tracking" if kind == "external_image" else "javascript:alert(1)"
        )
        entries["word/_rels/document.xml.rels"] = (
            '<Relationships><Relationship Type="http://example.org/' + relation_type + '" '
            'TargetMode="External" Target="' + target + '"/></Relationships>'
        ).encode()
    with ZipFile(source, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises(RenderError):
        check_renderable(source)


def test_renderer_copies_input_and_uses_isolated_profile(tmp_path, monkeypatch):
    source = make_resume(tmp_path / "master.docx")
    before = source.read_bytes()
    binary = tmp_path / "libreoffice"
    binary.write_text("synthetic executable placeholder")

    monkeypatch.setenv("API_TOKEN", "synthetic-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "synthetic-oauth-secret")

    def popen(arguments, **kwargs):
        assert "API_TOKEN" not in kwargs["env"]
        assert "GOOGLE_OAUTH_REFRESH_TOKEN" not in kwargs["env"]
        assert "--headless" in arguments
        assert any(a.startswith("-env:UserInstallation=file:") for a in arguments)
        assert str(source) not in arguments
        copied = Path(arguments[-1])
        assert copied.read_bytes() == before
        output = Path(arguments[arguments.index("--outdir") + 1]) / "document.pdf"
        output.write_bytes(pdf_scene())
        process = Mock(returncode=0)
        process.communicate.return_value = (b"", b"")
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    rendered = LibreOfficeRenderer(str(binary)).render(source)
    assert rendered.startswith(b"%PDF") and source.read_bytes() == before


def test_renderer_timeout_is_sanitized(tmp_path, monkeypatch):
    source = make_resume(tmp_path / "master.docx")
    binary = tmp_path / "libreoffice"
    binary.write_text("placeholder")
    process = Mock(pid=12345)
    process.communicate.side_effect = [subprocess.TimeoutExpired("private path", 1), (b"", b"")]
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    if hasattr(__import__("os"), "killpg"):
        monkeypatch.setattr("os.killpg", lambda *args: None)
    with pytest.raises(RenderError, match="renderer_timeout") as error:
        LibreOfficeRenderer(str(binary), timeout=1).render(source)
    assert "private path" not in str(error.value)


class SyntheticRenderer:
    version = "synthetic-test-renderer"

    def __init__(self, *, move=False):
        self.calls = 0
        self.move = move

    def render(self, path):
        self.calls += 1
        _, _, root = load_package(path)
        document = pymupdf.open()
        page = document.new_page(width=1200, height=800)
        for index, node in enumerate(root.iter(f"{{{W}}}t")):
            page.insert_text(
                (50, 30 + index * 20 + (10 if self.move and self.calls == 2 else 0)),
                (node.text or "").strip(),
                fontsize=8,
            )
        result = document.tobytes()
        document.close()
        return result


@pytest.fixture
def draft(app):
    root = Path(app.extensions["settings"].resume_storage_root)
    source = make_resume(root / "master.docx")
    with app.extensions["session_factory"].begin() as session:
        session.add(Profile(id="pdf-profile", name="Synthetic PDF profile"))
        session.flush()
        template, _ = import_template(session, root, source, "pdf-profile")
        field = next(f for f in template.manifest_json["fields"] if f["candidate"])
        authorize_fields(
            session, root, template.id, template.manifest_json["manifest_hash"], [field["field_id"]]
        )
        claim = "Built tested web apps with Python"
        fact = confirm_wording(
            session,
            root,
            template.id,
            template.manifest_json["manifest_hash"],
            field["field_id"],
            claim,
        )
        session.add(
            Job(
                id="pdf-job",
                source_id="fixture",
                external_id="pdf",
                canonical_url="https://example.org/pdf",
                company="Synthetic",
                title="Synthetic",
                description="Synthetic",
                status="active",
                last_verified_at=utcnow(),
                data={},
            )
        )
        session.flush()
        session.add(
            Match(
                job_id="pdf-job", profile_id="pdf-profile", score=90, hard_gate=False, evidence={}
            )
        )
        session.flush()
        variant, _ = create_variant(
            session,
            root,
            "pdf-job",
            template.id,
            [
                {
                    "field_id": field["field_id"],
                    "original_text": field["original_text"],
                    "proposed_text": claim,
                    "supporting_fact_ids": [fact.id],
                }
            ],
        )
        return root, variant.id, digest(source.read_bytes())


def test_validation_api_is_authenticated_idempotent_and_pdf_private(app, draft):
    root, variant_id, _ = draft
    client = app.test_client()
    path = f"/api/v1/resume-variants/{variant_id}/validate"
    headers = {"Authorization": "Bearer test-token"}
    assert client.post(path).status_code == 401
    assert client.post(path, headers=headers).status_code == 409
    configured = create_app(replace(app.extensions["settings"], resume_render_enabled=True))
    renderer = SyntheticRenderer()
    configured.extensions["document_renderer_factory"] = lambda: renderer
    client = configured.test_client()
    assert client.post(path, headers=headers, json={"visual": "passed"}).status_code == 400
    result = client.post(path, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json["state"] == "validated" and result.json["validation_complete"]
    assert result.json["can_approve_application"] is False
    assert client.post(path, headers=headers).json["sha256_pdf"] == result.json["sha256_pdf"]
    assert renderer.calls == 2
    pdf_path = f"/api/v1/resume-variants/{variant_id}/pdf"
    assert client.get(pdf_path).status_code == 401
    response = client.get(pdf_path, headers=headers)
    assert response.status_code == 200 and response.data.startswith(b"%PDF")
    with app.extensions["session_factory"]() as session:
        variant = session.get(ResumeVariant, variant_id)
        (root / variant.pdf_key).write_bytes(b"corrupted")
    assert client.get(pdf_path, headers=headers).status_code == 409
    configured.extensions["db_engine"].dispose()


def test_failed_layout_never_releases_variant(app, draft):
    root, variant_id, _ = draft
    with app.extensions["session_factory"].begin() as session:
        variant = validate_variant(session, root, variant_id, SyntheticRenderer(move=True))
        assert variant.state == "validation_failed"
        assert not validation_complete(variant)
        assert variant.validation_json["visual"]["status"] == "failed"


def test_converter_failure_is_recorded_without_false_success(app, draft):
    root, variant_id, _ = draft
    renderer = Mock(version="test-engine")
    renderer.render.side_effect = RenderError("renderer_timeout")
    with app.extensions["session_factory"].begin() as session:
        variant = validate_variant(session, root, variant_id, renderer)
        assert variant.state == "validation_failed"
        assert variant.validation_json["visual"]["code"] == "renderer_timeout"
        assert variant.pdf_key is None


def test_extra_pdf_claims_are_not_hidden_by_a_matching_prefix():
    report = compare_pdfs(pdf_scene(), pdf_scene(expand=True), MANIFEST, EDITS)
    assert report["pdf_ats"]["status"] == "failed"
    assert report["pdf_ats"]["unexpected_text"] is True


@pytest.mark.parametrize(
    "target", ["tel:+5500000000", "mailto:person@example.org", "https://example.org"]
)
def test_normal_cv_hyperlinks_are_preserved(tmp_path, target):
    source = make_resume(tmp_path / "links.docx")
    with ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/_rels/document.xml.rels"] = (
        '<Relationships><Relationship Type="http://example.org/hyperlink" '
        'TargetMode="External" Target="' + target + '"/></Relationships>'
    ).encode()
    with ZipFile(source, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    assert check_renderable(source) == source.read_bytes()


def test_external_resource_mode_is_checked_conservatively(tmp_path):
    source = make_resume(tmp_path / "external.docx")
    with ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Type="http://example.org/image" '
        b'TargetMode="external" Target="https://example.org/image.png"/></Relationships>'
    )
    with ZipFile(source, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    with pytest.raises(RenderError, match="external_document_resource_blocked"):
        check_renderable(source)
