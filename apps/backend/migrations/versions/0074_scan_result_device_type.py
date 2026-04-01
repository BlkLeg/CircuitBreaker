"""Add device_type and device_confidence columns to scan_results."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0074_scan_result_device_type"
down_revision = "0073_hardware_connection_ports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("scan_results")}
    if "device_type" not in cols:
        op.add_column("scan_results", sa.Column("device_type", sa.String(64), nullable=True))
    if "device_confidence" not in cols:
        op.add_column(
            "scan_results", sa.Column("device_confidence", sa.SmallInteger(), nullable=True)
        )


def downgrade() -> None:
    op.drop_column("scan_results", "device_confidence")
    op.drop_column("scan_results", "device_type")
