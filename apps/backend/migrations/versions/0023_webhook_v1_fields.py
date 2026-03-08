"""add webhook v1 fields

Revision ID: 0023_webhook_v1_fields
Revises: 0022_map_title
Create Date: 2026-03-08

"""

import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0023_webhook_v1_fields"
down_revision = "0022_map_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("webhook_rules")}
    dcols = {c["name"] for c in insp.get_columns("webhook_deliveries")}

    if "events_enabled" not in cols:
        op.add_column(
            "webhook_rules",
            sa.Column("events_enabled", sa.Text(), nullable=False, server_default="[]"),
        )
    if "headers_json" not in cols:
        op.add_column("webhook_rules", sa.Column("headers_json", sa.Text(), nullable=True))
    if "retries" not in cols:
        op.add_column(
            "webhook_rules",
            sa.Column("retries", sa.Integer(), nullable=False, server_default="3"),
        )
    if "updated_at" not in cols:
        op.add_column(
            "webhook_rules",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if "payload" not in dcols:
        op.add_column("webhook_deliveries", sa.Column("payload", sa.Text(), nullable=True))
    if "response_time_ms" not in dcols:
        op.add_column(
            "webhook_deliveries",
            sa.Column("response_time_ms", sa.Integer(), nullable=True),
        )

    # Backfill events_enabled from legacy topics where possible.
    rows = bind.execute(sa.text("SELECT id, topics FROM webhook_rules")).fetchall()
    for row in rows:
        topics = (row[1] or "").strip()
        if not topics:
            events = []
        else:
            events = [t.strip() for t in topics.split(",") if t.strip()]
        bind.execute(
            sa.text("UPDATE webhook_rules SET events_enabled = :events WHERE id = :id"),
            {"events": json.dumps(events), "id": row[0]},
        )


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "response_time_ms")
    op.drop_column("webhook_deliveries", "payload")
    op.drop_column("webhook_rules", "updated_at")
    op.drop_column("webhook_rules", "retries")
    op.drop_column("webhook_rules", "headers_json")
    op.drop_column("webhook_rules", "events_enabled")
