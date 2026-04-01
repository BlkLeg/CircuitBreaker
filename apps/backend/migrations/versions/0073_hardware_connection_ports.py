"""Add source_port and target_port columns to hardware_connections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0073_hardware_connection_ports"
down_revision = "0072_lldp_scan_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("hardware_connections")}
    if "source_port" not in cols:
        op.add_column("hardware_connections", sa.Column("source_port", sa.String(), nullable=True))
    if "target_port" not in cols:
        op.add_column("hardware_connections", sa.Column("target_port", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("hardware_connections", "target_port")
    op.drop_column("hardware_connections", "source_port")
