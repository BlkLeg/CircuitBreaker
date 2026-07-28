"""Add agent_server_private_key column to app_settings.

Revision ID: 0090_agent_server_private_key
Revises: 0089_agents
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0090_agent_server_private_key"
down_revision = "0089_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "agent_server_private_key" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("agent_server_private_key", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("app_settings", "agent_server_private_key")
