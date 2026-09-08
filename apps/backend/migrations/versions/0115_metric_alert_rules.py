"""Add metric alert rules, restart-safe state, and transition outbox.

Revision ID: 0115_metric_alert_rules
Revises: 0114_inventory_transfer
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = "0115_metric_alert_rules"
down_revision = "0114_inventory_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded per table, the way 0114 guards its own two. A fresh install gets
    # its whole schema from `0001_init`, which calls `create_all()` over the
    # *live* ORM metadata — and `db/models/monitors.py` declares all three of
    # these tables, so they already exist by the time this revision runs.
    # Unguarded, `alembic upgrade head` failed on every fresh database.
    tables = set(sa_inspect(op.get_bind()).get_table_names())

    if "metric_alert_rules" not in tables:
        op.create_table(
            "metric_alert_rules",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column(
                "target_type", sa.String(length=32), server_default="hardware", nullable=False
            ),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column("metric_key", sa.String(length=32), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=True),
            sa.Column("comparator", sa.String(length=4), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(length=16), nullable=False),
            sa.Column("breach_duration_s", sa.Integer(), server_default="300", nullable=False),
            sa.Column("recovery_threshold", sa.Float(), nullable=False),
            sa.Column("recovery_duration_s", sa.Integer(), server_default="300", nullable=False),
            sa.Column("max_gap_s", sa.Integer(), server_default="180", nullable=False),
            sa.Column("freshness_s", sa.Integer(), server_default="180", nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("severity", sa.String(length=16), server_default="warning", nullable=False),
            sa.Column("sink_id", sa.Integer(), nullable=True),
            sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["sink_id"], ["notification_sinks.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_metric_alert_rules_target_id", "metric_alert_rules", ["target_id"])

    if "metric_alert_states" not in tables:
        op.create_table(
            "metric_alert_states",
            sa.Column("rule_id", sa.Integer(), nullable=False),
            sa.Column("rule_revision", sa.Integer(), nullable=False),
            sa.Column("assessment", sa.String(length=16), server_default="unknown", nullable=False),
            sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recovery_since", sa.DateTime(timezone=True), nullable=True),
            sa.Column("open_incident_id", sa.String(length=32), nullable=True),
            sa.Column("last_sample_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["rule_id"], ["metric_alert_rules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("rule_id"),
        )

    if "metric_alert_events" not in tables:
        op.create_table(
            "metric_alert_events",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("transition_key", sa.String(length=160), nullable=False),
            sa.Column("rule_id", sa.Integer(), nullable=False),
            sa.Column("rule_revision", sa.Integer(), nullable=False),
            sa.Column("incident_id", sa.String(length=32), nullable=False),
            sa.Column("event_type", sa.String(length=16), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column(
                "publish_state", sa.String(length=16), server_default="pending", nullable=False
            ),
            sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["rule_id"], ["metric_alert_rules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("transition_key", name="uq_metric_alert_events_transition_key"),
        )
        op.create_index(
            "ix_metric_alert_events_publish",
            "metric_alert_events",
            ["publish_state", "occurred_at"],
        )


def downgrade() -> None:
    op.drop_table("metric_alert_events")
    op.drop_table("metric_alert_states")
    op.drop_table("metric_alert_rules")
