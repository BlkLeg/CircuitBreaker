"""Add graph_uplink_overrides to app_settings for persisting uplink speeds on non-hardware nodes.

Revision ID: 0031_graph_uplink_overrides
Revises: 0030_proxmox_discover_runs
Create Date: 2026-03-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0031_graph_uplink_overrides"
down_revision = "0030_proxmox_discover_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("app_settings"):
        return
    cols = {c["name"] for c in sa.inspect(bind).get_columns("app_settings")}
    if "graph_uplink_overrides" in cols:
        return
    op.add_column(
        "app_settings",
        sa.Column("graph_uplink_overrides", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "graph_uplink_overrides")
