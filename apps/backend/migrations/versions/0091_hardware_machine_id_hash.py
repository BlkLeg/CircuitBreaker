"""Add machine_id_hash column to hardware.

Revision ID: 0091_hardware_machine_id_hash
Revises: 0090_agent_server_private_key
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0091_hardware_machine_id_hash"
down_revision = "0090_agent_server_private_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("hardware")}
    if "machine_id_hash" not in cols:
        op.add_column(
            "hardware",
            sa.Column("machine_id_hash", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_hardware_machine_id_hash",
            "hardware",
            ["machine_id_hash"],
            if_not_exists=True,
        )


def downgrade() -> None:
    op.drop_index("ix_hardware_machine_id_hash", table_name="hardware", if_exists=True)
    op.drop_column("hardware", "machine_id_hash")
