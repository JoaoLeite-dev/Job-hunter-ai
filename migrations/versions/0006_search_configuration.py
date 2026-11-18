"""Versioned search preferences persisted in the local database."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_configurations",
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("search_configurations")
