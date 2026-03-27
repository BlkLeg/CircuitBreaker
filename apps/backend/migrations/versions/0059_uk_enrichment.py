"""Uptime Kuma Phase 2: enrich integration_monitors with response time,
cert expiry, hardware linkage, and last heartbeat timestamp."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0059_uk_enrichment"
down_revision = "0058_intel_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    existing_cols = {c["name"] for c in insp.get_columns("integration_monitors")}

    if "avg_response_ms" not in existing_cols:
        op.add_column(
            "integration_monitors",
            sa.Column("avg_response_ms", sa.Float(), nullable=True),
        )
    if "cert_expiry_days" not in existing_cols:
        op.add_column(
            "integration_monitors",
            sa.Column("cert_expiry_days", sa.Integer(), nullable=True),
        )
    if "linked_hardware_id" not in existing_cols:
        op.add_column(
            "integration_monitors",
            sa.Column(
                "linked_hardware_id",
                sa.Integer(),
                sa.ForeignKey("hardware.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    existing_indexes = {idx["name"] for idx in insp.get_indexes("integration_monitors")}
    if "ix_intmon_linked_hw" not in existing_indexes:
        op.create_index("ix_intmon_linked_hw", "integration_monitors", ["linked_hardware_id"])
    if "last_heartbeat_at" not in existing_cols:
        op.add_column(
            "integration_monitors",
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("integration_monitors", "last_heartbeat_at")
    op.drop_index("ix_intmon_linked_hw", table_name="integration_monitors")
    op.drop_column("integration_monitors", "linked_hardware_id")
    op.drop_column("integration_monitors", "cert_expiry_days")
    op.drop_column("integration_monitors", "avg_response_ms")
