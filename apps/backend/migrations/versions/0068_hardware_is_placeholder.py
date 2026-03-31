"""Add is_placeholder column to hardware table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0068_hardware_is_placeholder"
down_revision = "0067_oauth_state_nonce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("hardware")}
    if "is_placeholder" not in cols:
        op.add_column(
            "hardware",
            sa.Column("is_placeholder", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    op.drop_column("hardware", "is_placeholder")
