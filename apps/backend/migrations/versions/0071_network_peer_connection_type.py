"""Add connection_type and bandwidth_mbps to network_peers

Revision ID: 0071_network_peer_connection_type
Revises: 0070_arp_enabled_default_false
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0071_network_peer_connection_type"
down_revision = "0070_arp_enabled_default_false"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        current_schema = "public"

    # Idempotent: skip if columns already exist (e.g. created by metadata.create_all
    # on a fresh install before Alembic stamps this revision).
    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".network_peers '
            "ADD COLUMN IF NOT EXISTS connection_type VARCHAR"
        )
    )
    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".network_peers '
            "ADD COLUMN IF NOT EXISTS bandwidth_mbps INTEGER"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        current_schema = "public"

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".network_peers DROP COLUMN IF EXISTS bandwidth_mbps'
        )
    )
    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".network_peers DROP COLUMN IF EXISTS connection_type'
        )
    )
