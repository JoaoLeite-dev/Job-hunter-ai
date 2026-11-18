"""Retry metadata for the projection outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("sync_outbox", sa.Column("last_error_code", sa.String(100)))
    op.add_column(
        "sync_outbox",
        sa.Column("terminal_failure", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_sync_outbox_pending", "sync_outbox", ["processed_at", "next_attempt_at", "attempts"]
    )


def downgrade() -> None:
    op.drop_index("ix_sync_outbox_pending", table_name="sync_outbox")
    op.drop_column("sync_outbox", "terminal_failure")
    op.drop_column("sync_outbox", "last_error_code")
    op.drop_column("sync_outbox", "next_attempt_at")
