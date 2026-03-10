"""Add VLAN support to discovery

Revision ID: a3b4c5d6e7fa
Revises: a3b4c5d6e7f9
Create Date: 2026-03-07 19:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7fa"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade():
    # discovery_profiles
    op.add_column("discovery_profiles", sa.Column("vlan_ids", sa.String(), nullable=True))
    with op.batch_alter_table("discovery_profiles") as batch_op:
        batch_op.alter_column("cidr", existing_type=sa.String(), nullable=True)

    # scan_jobs
    op.add_column("scan_jobs", sa.Column("vlan_ids", sa.String(), nullable=True))
    op.add_column("scan_jobs", sa.Column("network_ids", sa.String(), nullable=True))
    with op.batch_alter_table("scan_jobs") as batch_op:
        batch_op.alter_column("target_cidr", existing_type=sa.String(), nullable=True)

    # scan_results
    op.add_column("scan_results", sa.Column("vlan_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("scan_results") as batch_op:
        # Since SQLite might balk at adding a foreign key on an existing table without batch,
        # we do it here or just add a simple column if we don't care about strict constraints.
        # But add_column works with FK in modern SQLAlchemy usually, let's use batch_op though.
        batch_op.add_column(
            sa.Column("network_id", sa.Integer(), sa.ForeignKey("networks.id"), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("scan_results") as batch_op:
        batch_op.drop_column("network_id")
        batch_op.drop_column("vlan_id")

    with op.batch_alter_table("scan_jobs") as batch_op:
        batch_op.alter_column("target_cidr", existing_type=sa.String(), nullable=False)
        batch_op.drop_column("network_ids")
        batch_op.drop_column("vlan_ids")

    with op.batch_alter_table("discovery_profiles") as batch_op:
        batch_op.alter_column("cidr", existing_type=sa.String(), nullable=False)
        batch_op.drop_column("vlan_ids")
