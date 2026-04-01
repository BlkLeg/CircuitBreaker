"""Add lldp_neighbors_json column to scan_results."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "0072_lldp_scan_result"
down_revision = "0071_network_peer_connection_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("scan_results")}
    if "lldp_neighbors_json" not in cols:
        op.add_column("scan_results", sa.Column("lldp_neighbors_json", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_results", "lldp_neighbors_json")
