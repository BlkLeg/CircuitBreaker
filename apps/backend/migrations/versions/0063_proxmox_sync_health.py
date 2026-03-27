"""Add last_sync_error and last_poll_error to integration_configs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0063_proxmox_sync_health"
down_revision = "0062_native_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    existing_cols = {c["name"] for c in insp.get_columns("integration_configs")}

    if "last_sync_error" not in existing_cols:
        op.add_column(
            "integration_configs",
            sa.Column("last_sync_error", sa.Text(), nullable=True),
        )
    if "last_poll_error" not in existing_cols:
        op.add_column(
            "integration_configs",
            sa.Column("last_poll_error", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("integration_configs", "last_poll_error")
    op.drop_column("integration_configs", "last_sync_error")
