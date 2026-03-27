"""Add notes to ip_addresses and site_id to networks."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0066_ipam_notes_network_site"
down_revision = "0065_multi_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)

    if "notes" not in {c["name"] for c in insp.get_columns("ip_addresses")}:
        op.add_column(
            "ip_addresses",
            sa.Column("notes", sa.Text(), nullable=True),
        )
    if "site_id" not in {c["name"] for c in insp.get_columns("networks")}:
        op.add_column(
            "networks",
            sa.Column("site_id", sa.Integer(), nullable=True),
        )
    networks_fks = {fk["name"] for fk in insp.get_foreign_keys("networks")}
    if "fk_networks_site_id" not in networks_fks:
        op.create_foreign_key(
            "fk_networks_site_id",
            "networks",
            "sites",
            ["site_id"],
            ["id"],
            ondelete="SET NULL",
        )
    existing_indexes = {idx["name"] for idx in insp.get_indexes("networks")}
    if "ix_networks_site_id" not in existing_indexes:
        op.create_index("ix_networks_site_id", "networks", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_networks_site_id", table_name="networks")
    op.drop_constraint("fk_networks_site_id", "networks", type_="foreignkey")
    op.drop_column("networks", "site_id")
    op.drop_column("ip_addresses", "notes")
