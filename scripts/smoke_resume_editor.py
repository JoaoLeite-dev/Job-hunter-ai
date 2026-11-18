"""PostgreSQL draft-editor smoke using synthetic OOXML only."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from job_hunter.application.resume_variants import (
    confirm_template_facts,
    confirm_wording,
    create_variant,
    verify_current_variant,
)
from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.infrastructure.db import Job, Match, Profile, ResumeVariant, VerifiedFact, utcnow
from job_hunter.infrastructure.resumes import ResumeError, W, digest


def fixture(path):
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types><Override PartName="/word/document.xml" '
            f'ContentType="{content_type}"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            "<Relationships><Relationship "
            f'Type="{rel_type}" Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}"><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            "<w:r><w:t>Resumo profissional</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Built responsive web applications using Python and React libraries"
            "</w:t></w:r></w:p></w:body></w:document>",
        )


original_url = os.environ["DATABASE_URL"]
assert original_url.startswith("postgresql")
schema = "smoke_editor_" + uuid4().hex
root_engine = create_engine(original_url)
test_url = make_url(original_url).update_query_dict({"options": "-csearch_path=" + schema})
engine = create_engine(test_url)
try:
    with root_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with TemporaryDirectory(prefix="smoke_editor_") as temporary:
        root = Path(temporary)
        source = root / "synthetic.docx"
        fixture(source)
        before = digest(source.read_bytes())
        with Session(engine) as session, session.begin():
            session.add(Profile(id="synthetic", name="Synthetic editor test"))
            session.flush()
            template, _ = import_template(session, root, source, "synthetic")
            field = next(f for f in template.manifest_json["fields"] if f["candidate"])
            authorize_fields(
                session,
                root,
                template.id,
                template.manifest_json["manifest_hash"],
                [field["field_id"]],
            )
            confirm_template_facts(
                session, root, template.id, template.manifest_json["manifest_hash"]
            )
            claim = "Built tested web applications with Python"
            fact = confirm_wording(
                session,
                root,
                template.id,
                template.manifest_json["manifest_hash"],
                field["field_id"],
                claim,
            )
            fact_id = fact.id
            template_id = template.id
            edits = [
                {
                    "field_id": field["field_id"],
                    "original_text": field["original_text"],
                    "proposed_text": claim,
                    "supporting_fact_ids": [fact_id],
                }
            ]
            session.add(
                Job(
                    id="job",
                    source_id="fixture",
                    external_id="one",
                    canonical_url="https://example.org/job",
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
                Match(job_id="job", profile_id="synthetic", score=90, hard_gate=False, evidence={})
            )
        with Session(engine) as session, session.begin():
            variant, created = create_variant(session, root, "job", template_id, edits)
            assert created and variant.state == "validation_pending"
            variant_id = variant.id
            assert variant.validation_json["visual"]["status"] == "not_run"
        with Session(engine) as session, session.begin():
            variant, created = create_variant(session, root, "job", template_id, edits)
            assert not created and variant.id == variant_id
            verify_current_variant(session, root, variant)
            session.get(VerifiedFact, fact_id).verified_at = None
        with Session(engine) as session, session.begin():
            variant = session.get(ResumeVariant, variant_id)
            try:
                verify_current_variant(session, root, variant)
            except ResumeError:
                pass
            else:
                raise AssertionError("Revoked evidence accepted")
        assert digest(source.read_bytes()) == before
    command.downgrade(cfg, "0003")
    command.upgrade(cfg, "head")
    command.check(cfg)
    print("PASS: PostgreSQL draft editor, evidence revocation, idempotency and master integrity")
finally:
    os.environ["DATABASE_URL"] = original_url
    engine.dispose()
    assert schema.startswith("smoke_editor_") and len(schema) == len("smoke_editor_") + 32
    with root_engine.begin() as connection:
        connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    root_engine.dispose()
