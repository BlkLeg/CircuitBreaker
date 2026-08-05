"""Add pending_update_version column to agents (Task 24).

Revision ID: 0092_agent_pending_update_version
Revises: 0091_hardware_machine_id_hash
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0092_agent_pending_update_version"
down_revision = "0091_hardware_machine_id_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "pending_update_version" not in cols:
        op.add_column(
            "agents",
            sa.Column("pending_update_version", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agents", "pending_update_version")
