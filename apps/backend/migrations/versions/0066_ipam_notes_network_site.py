"""Add notes to ip_addresses and site_id to networks."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0066_ipam_notes_network_site"
down_revision = "0065_multi_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ip_addresses",
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "networks",
        sa.Column("site_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_networks_site_id",
        "networks",
        "sites",
        ["site_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_networks_site_id", "networks", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_networks_site_id", table_name="networks")
    op.drop_constraint("fk_networks_site_id", "networks", type_="foreignkey")
    op.drop_column("networks", "site_id")
    op.drop_column("ip_addresses", "notes")
