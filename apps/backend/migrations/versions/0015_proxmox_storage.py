"""Add Proxmox fields to storage table

Revision ID: a3b4c5d6e7fc
Revises: a3b4c5d6e7fb
Create Date: 2026-03-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7fc"
down_revision = "a3b4c5d6e7fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "storage",
        sa.Column(
            "integration_config_id",
            sa.Integer(),
            sa.ForeignKey("integration_configs.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "storage",
        sa.Column("proxmox_storage_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("storage", "proxmox_storage_name")
    op.drop_column("storage", "integration_config_id")
