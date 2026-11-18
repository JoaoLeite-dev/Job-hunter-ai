"""Index actual publication dates; never infer them from discovery timestamps."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_published_at", "jobs", ["published_at"])
    table = sa.table(
        "jobs",
        sa.column("id", sa.String),
        sa.column("data", sa.JSON),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    for identity, data in bind.execute(sa.select(table.c.id, table.c.data)).all():
        value = data.get("published_at") if isinstance(data, dict) else None
        if not isinstance(value, str) or len(value) > 100:
            continue
        try:
            published = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        bind.execute(table.update().where(table.c.id == identity).values(published_at=published))


def downgrade():
    op.drop_index("ix_jobs_published_at", table_name="jobs")
    op.drop_column("jobs", "published_at")
