"""Private drafts and their evidence snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "template_id", sa.String(36), sa.ForeignKey("resume_templates.id"), nullable=False
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("docx_key", sa.Text(), nullable=False),
        sa.Column("pdf_key", sa.Text()),
        sa.Column("sha256_docx", sa.String(64), nullable=False),
        sa.Column("sha256_pdf", sa.String(64)),
        sa.Column("edits_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.UniqueConstraint("job_id", "template_id", "request_hash", name="uq_variant_request"),
    )


def downgrade() -> None:
    op.drop_table("resume_variants")
