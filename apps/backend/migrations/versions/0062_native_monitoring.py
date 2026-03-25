"""Native monitoring — probe config columns, event annotations, auto_monitor_on_discovery."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0062_native_monitoring"
down_revision = "0061_invite_oauth_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── integration_monitors: probe configuration ──────────────────────────
    op.add_column(
        "integration_monitors",
        sa.Column("linked_service_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_intmon_service_id",
        "integration_monitors",
        "services",
        ["linked_service_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "integration_monitors",
        sa.Column("probe_type", sa.String(), nullable=True),
    )
    op.add_column(
        "integration_monitors",
        sa.Column("probe_target", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_monitors",
        sa.Column("probe_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "integration_monitors",
        sa.Column(
            "probe_interval_s",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )

    # ── integration_monitor_events: annotation fields ──────────────────────
    op.add_column(
        "integration_monitor_events",
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_monitor_events",
        sa.Column("reason_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_intmon_evt_reason_by",
        "integration_monitor_events",
        "users",
        ["reason_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "integration_monitor_events",
        sa.Column("reason_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── app_settings: discovery auto-pipeline toggle ───────────────────────
    op.add_column(
        "app_settings",
        sa.Column(
            "auto_monitor_on_discovery",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "auto_monitor_on_discovery")
    op.drop_constraint("fk_intmon_evt_reason_by", "integration_monitor_events", type_="foreignkey")
    op.drop_column("integration_monitor_events", "reason_at")
    op.drop_column("integration_monitor_events", "reason_by")
    op.drop_column("integration_monitor_events", "reason")
    op.drop_constraint("fk_intmon_service_id", "integration_monitors", type_="foreignkey")
    op.drop_column("integration_monitors", "probe_interval_s")
    op.drop_column("integration_monitors", "probe_port")
    op.drop_column("integration_monitors", "probe_target")
    op.drop_column("integration_monitors", "probe_type")
    op.drop_column("integration_monitors", "linked_service_id")
