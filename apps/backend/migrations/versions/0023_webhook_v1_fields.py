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
    tables = set(insp.get_table_names())

    # Handle DBs stamped to 0022 without running 0017/0016 (missing webhook tables).
    if "webhook_rules" not in tables:
        op.create_table(
            "webhook_rules",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("target_url", sa.String(), nullable=False),
            sa.Column("secret", sa.String(), nullable=True),
            sa.Column("topics", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("events_enabled", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("headers_json", sa.Text(), nullable=True),
            sa.Column("retries", sa.Integer(), nullable=False, server_default="3"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "webhook_deliveries" not in tables:
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "rule_id",
                sa.Integer(),
                sa.ForeignKey("webhook_rules.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=False, default=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.String(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("response_time_ms", sa.Integer(), nullable=True),
        )
        op.create_index("ix_webhook_deliveries_rule_id", "webhook_deliveries", ["rule_id"])
        op.create_index(
            "ix_webhook_deliveries_delivered_at", "webhook_deliveries", ["delivered_at"]
        )
    else:
        dcols = {c["name"] for c in insp.get_columns("webhook_deliveries")}
        if "payload" not in dcols:
            op.add_column("webhook_deliveries", sa.Column("payload", sa.Text(), nullable=True))
        if "response_time_ms" not in dcols:
            op.add_column(
                "webhook_deliveries",
                sa.Column("response_time_ms", sa.Integer(), nullable=True),
            )

    cols = {c["name"] for c in insp.get_columns("webhook_rules")}
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

    # Backfill events_enabled from legacy topics where possible.
    # Re-read columns in case the table was just created above.
    refreshed_cols = {c["name"] for c in insp.get_columns("webhook_rules")}
    if "topics" not in refreshed_cols:
        return

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
