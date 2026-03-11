"""Add proxmox_discover_runs table for Proxmox discovery history.

Revision ID: 0030_proxmox_discover_runs
Revises: 0029_fix_jsonb_column_defaults
Create Date: 2026-03-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030_proxmox_discover_runs"
down_revision = "0029_fix_jsonb_column_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("proxmox_discover_runs"):
        return  # already applied (e.g. table created by a previous run)
    op.create_table(
        "proxmox_discover_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nodes_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vms_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cts_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("networks_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["integration_id"], ["integration_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_proxmox_discover_runs_id"),
        "proxmox_discover_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_proxmox_discover_runs_integration_id"),
        "proxmox_discover_runs",
        ["integration_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_proxmox_discover_runs_integration_id"), table_name="proxmox_discover_runs"
    )
    op.drop_index(op.f("ix_proxmox_discover_runs_id"), table_name="proxmox_discover_runs")
    op.drop_table("proxmox_discover_runs")
