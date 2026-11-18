"""Private DOCX import smoke in a disposable PostgreSQL schema; never edits CV content.

Provide only the source filename as the first argument. The file must already be
in RESUME_STORAGE_ROOT. No professional facts or editable fields are authorized.
"""

import os
import sys
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from job_hunter.application.resumes import authorize_fields, import_template
from job_hunter.infrastructure.db import Profile, ResumeTemplate, VerifiedFact
from job_hunter.infrastructure.resumes import ResumeError, digest, resolve_source

original_url = os.environ["DATABASE_URL"]
assert original_url.startswith("postgresql")
root = Path(os.environ["RESUME_STORAGE_ROOT"])
source = resolve_source(root, sys.argv[1])
before = digest(source.read_bytes())
schema = "smoke_resume_" + uuid4().hex
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
    with Session(engine) as session, session.begin():
        session.add(Profile(id="private-smoke", name="Temporary private import test"))
    with Session(engine) as session, session.begin():
        template, created = import_template(session, root, source, "private-smoke")
        assert created and not template.active and template.manifest_json["approval"] is None
        template_id = template.id
    with Session(engine) as session, session.begin():
        template, created = import_template(session, root, source, "private-smoke")
        assert not created and template.id == template_id
        assert session.scalar(select(func.count()).select_from(ResumeTemplate)) == 1
        assert session.scalar(select(func.count()).select_from(VerifiedFact)) == 0
        manifest = template.manifest_json
        protected = next(f["field_id"] for f in manifest["fields"] if not f["candidate"])
        try:
            authorize_fields(session, root, template.id, manifest["manifest_hash"], [protected])
        except ResumeError as error:
            assert str(error) == "protected_field_selected"
        else:
            raise AssertionError("Protected field was authorized")
        assert not template.active and template.manifest_json["approval"] is None
        assert digest((root / template.storage_key).read_bytes()) == before
    assert digest(source.read_bytes()) == before
    command.downgrade(cfg, "0002")
    command.upgrade(cfg, "head")
    command.check(cfg)
    print("PASS: master unchanged, idempotent import, protected fields and PostgreSQL")
finally:
    os.environ["DATABASE_URL"] = original_url
    engine.dispose()
    assert schema.startswith("smoke_resume_") and len(schema) == len("smoke_resume_") + 32
    with root_engine.begin() as connection:
        connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    root_engine.dispose()
