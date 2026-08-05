"""Add pending_device_pk / pending_device_pk_expiry columns to agents (Task 27).

Revision ID: 0093_agent_pending_device_key
Revises: 0092_agent_pending_update_version
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0093_agent_pending_device_key"
down_revision = "0092_agent_pending_update_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "pending_device_pk" not in cols:
        op.add_column(
            "agents",
            sa.Column("pending_device_pk", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_agents_pending_device_pk",
            "agents",
            ["pending_device_pk"],
            if_not_exists=True,
        )
    if "pending_device_pk_expiry" not in cols:
        op.add_column(
            "agents",
            sa.Column("pending_device_pk_expiry", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agents", "pending_device_pk_expiry")
    op.drop_index("ix_agents_pending_device_pk", table_name="agents", if_exists=True)
    op.drop_column("agents", "pending_device_pk")
