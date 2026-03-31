"""Add source column to hardware_connections table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0069_hardware_connection_source"
down_revision = "0068_hardware_is_placeholder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("hardware_connections")}
    if "source" not in cols:
        op.add_column(
            "hardware_connections",
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="manual",
            ),
        )


def downgrade() -> None:
    op.drop_column("hardware_connections", "source")
