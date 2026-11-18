"""Real LibreOffice/PDF/PostgreSQL smoke, using only synthetic CV content."""

import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

import pymupdf
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from job_hunter import create_app
from job_hunter.application.resume_variants import confirm_wording, create_variant
from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.config import Settings
from job_hunter.infrastructure.db import Job, Match, Profile, ResumeTemplate, utcnow
from job_hunter.infrastructure.resumes import W, digest


def make_fixture(path):
    ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    main = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'
        for style, text in [
            ("Title", "Synthetic Person"),
            ("Heading1", "Resumo profissional"),
            ("Normal", "Built responsive web applications using Python and React libraries"),
            ("Heading1", "Experiencia profissional"),
            ("Normal", "Engineer | Synthetic Company"),
            ("Normal", "2022 to present"),
            ("ListBullet", "Developed secure integrations and accessible web applications"),
        ]
    )
    styles = (
        f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Liberation Sans" w:hAnsi="Liberation Sans"/>'
        '<w:sz w:val="20"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style></w:styles>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="{ct}">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main}"/>'
            '<Override PartName="/word/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{rel}">'
            f'<Relationship Id="rId1" Type="{office}officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            f'<Relationships xmlns="{rel}">'
            f'<Relationship Id="rId2" Type="{office}styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("word/styles.xml", styles)
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}"><w:body>{body}'
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="720" w:bottom="720" w:left="720" w:right="720"/>'
            "</w:sectPr></w:body></w:document>",
        )


original_url = os.environ["DATABASE_URL"]
assert original_url.startswith("postgresql")
schema = "smoke_pdf_" + uuid4().hex
root_engine = create_engine(original_url)
test_url = make_url(original_url).update_query_dict({"options": "-csearch_path=" + schema})
engine = create_engine(test_url)
qa_root = Path(os.environ["RESUME_STORAGE_ROOT"]) / "qa" / "synthetic-render"
qa_root.mkdir(parents=True, exist_ok=True)
try:
    with root_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with TemporaryDirectory(prefix="smoke_pdf_") as temporary:
        root = Path(temporary)
        source = root / "synthetic.docx"
        make_fixture(source)
        before = digest(source.read_bytes())
        with Session(engine) as session, session.begin():
            session.add(Profile(id="synthetic-pdf", name="Synthetic rendering test"))
            session.flush()
            template, _ = import_template(session, root, source, "synthetic-pdf")
            field = next(f for f in template.manifest_json["fields"] if f["candidate"])
            template_id = template.id
            authorize_fields(
                session,
                root,
                template.id,
                template.manifest_json["manifest_hash"],
                [field["field_id"]],
            )
            session.add(
                Job(
                    id="job",
                    source_id="fixture",
                    external_id="render",
                    canonical_url="https://example.org/render",
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
                    job_id="job", profile_id="synthetic-pdf", score=90, hard_gate=False, evidence={}
                )
            )
        app = create_app(
            replace(Settings.from_env(), resume_storage_root=str(root), resume_render_enabled=True)
        )
        client = app.test_client()
        headers = {"Authorization": "Bearer " + os.environ["API_TOKEN"]}
        reports = []
        for index, claim in enumerate(
            ["Built tested web applications with Python", "W" * field["max_characters"]]
        ):
            with Session(engine) as session, session.begin():
                template = session.get(ResumeTemplate, template_id)
                fact = confirm_wording(
                    session,
                    root,
                    template_id,
                    template.manifest_json["manifest_hash"],
                    field["field_id"],
                    claim,
                )
                variant, _ = create_variant(
                    session,
                    root,
                    "job",
                    template_id,
                    [
                        {
                            "field_id": field["field_id"],
                            "original_text": field["original_text"],
                            "proposed_text": claim,
                            "supporting_fact_ids": [fact.id],
                        }
                    ],
                )
                variant_id = variant.id
            path = f"/api/v1/resume-variants/{variant_id}"
            response = client.post(path + "/validate", headers=headers)
            assert response.status_code == 200, response.json
            reports.append(response.json)
            if index == 0:
                assert response.json["validation_complete"], response.json
                pdf = client.get(path + "/pdf", headers=headers)
                assert pdf.status_code == 200
                assert client.get(path + "/pdf").status_code == 401
                assert (
                    client.post(path + "/validate", headers=headers).json["sha256_pdf"]
                    == response.json["sha256_pdf"]
                )
                (qa_root / "variant.pdf").write_bytes(pdf.data)
                with pymupdf.open(stream=pdf.data, filetype="pdf") as document:
                    for page_index, page in enumerate(document):
                        page.get_pixmap(dpi=120).save(
                            str(qa_root / f"variant-{page_index + 1}.png")
                        )
            else:
                assert not response.json["validation_complete"]
                assert response.json["state"] == "validation_failed"
                assert response.json["validation"]["visual"]["status"] == "failed"
        assert digest(source.read_bytes()) == before
        renderer = app.extensions["document_renderer_factory"]()
        baseline = renderer.render(source)
        (qa_root / "baseline.pdf").write_bytes(baseline)
        with pymupdf.open(stream=baseline, filetype="pdf") as document:
            for index, page in enumerate(document):
                page.get_pixmap(dpi=120).save(str(qa_root / f"baseline-{index + 1}.png"))
        (qa_root / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        app.extensions["db_engine"].dispose()
    print("PASS: real LibreOffice, PDF text/layout gates, private HTTP download and PostgreSQL")
finally:
    os.environ["DATABASE_URL"] = original_url
    engine.dispose()
    assert schema.startswith("smoke_pdf_") and len(schema) == len("smoke_pdf_") + 32
    with root_engine.begin() as connection:
        connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    root_engine.dispose()
