"""Persistent local public-source cache and cross-process request budget."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_cache",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("next_request_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON()),
        sa.Column("error_code", sa.String(100)),
    )


def downgrade():
    op.drop_table("source_cache")
