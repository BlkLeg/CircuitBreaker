"""Task 28: server-key rotation with overlap window.

Adds the successor-key + overlap-timing columns to app_settings (mirroring
agent_server_private_key's existing vault-encrypted-Text convention), and the
per-agent "which server key did this agent's most recent handshake pin"
timestamp columns to agents.

Revision ID: 0094_agent_server_key_rotation
Revises: 0093_agent_pending_device_key
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0094_agent_server_key_rotation"
down_revision = "0093_agent_pending_device_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)

    settings_cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "agent_server_key_pending_private_key" not in settings_cols:
        op.add_column(
            "app_settings",
            sa.Column("agent_server_key_pending_private_key", sa.Text(), nullable=True),
        )
    if "agent_server_key_rotation_started_at" not in settings_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "agent_server_key_rotation_started_at", sa.DateTime(timezone=True), nullable=True
            ),
        )
    if "agent_server_key_rotation_overlap_expires_at" not in settings_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "agent_server_key_rotation_overlap_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    agents_cols = {c["name"] for c in insp.get_columns("agents")}
    if "server_pk_current_pinned_at" not in agents_cols:
        op.add_column(
            "agents",
            sa.Column("server_pk_current_pinned_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "server_pk_successor_pinned_at" not in agents_cols:
        op.add_column(
            "agents",
            sa.Column("server_pk_successor_pinned_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("agents", "server_pk_successor_pinned_at")
    op.drop_column("agents", "server_pk_current_pinned_at")
    op.drop_column("app_settings", "agent_server_key_rotation_overlap_expires_at")
    op.drop_column("app_settings", "agent_server_key_rotation_started_at")
    op.drop_column("app_settings", "agent_server_key_pending_private_key")
