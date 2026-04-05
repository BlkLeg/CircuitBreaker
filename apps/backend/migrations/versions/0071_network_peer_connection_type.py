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
    existing = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='network_peers'"
            )
        )
    }
    with op.batch_alter_table("network_peers") as batch_op:
        if "connection_type" not in existing:
            batch_op.add_column(sa.Column("connection_type", sa.String(), nullable=True))
        if "bandwidth_mbps" not in existing:
            batch_op.add_column(sa.Column("bandwidth_mbps", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("network_peers") as batch_op:
        batch_op.drop_column("bandwidth_mbps")
        batch_op.drop_column("connection_type")
