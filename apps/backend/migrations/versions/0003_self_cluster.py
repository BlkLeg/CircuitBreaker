"""Self-aware cluster topology — v0.2.0

Revision ID: e7f2a1c3b4d5
Revises: c3f1a2b4d5e6
Create Date: 2026-03-06 00:00:00.000000

Changes:
- hardware_clusters: add `type` column
- hardware_cluster_members: make hardware_id nullable; add member_type, service_id columns
- services: add docker_labels column (JSON text)
- app_settings: add self_cluster_enabled flag
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7f2a1c3b4d5"
down_revision = "c3f1a2b4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # hardware_clusters.type
    op.add_column(
        "hardware_clusters",
        sa.Column("type", sa.String(), server_default="manual", nullable=True),
    )

    # hardware_cluster_members: make hardware_id nullable + add member_type + service_id
    # SQLite requires batch mode to alter existing column nullability
    with op.batch_alter_table("hardware_cluster_members", recreate="auto") as batch_op:
        batch_op.alter_column("hardware_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(
            sa.Column("member_type", sa.String(), server_default="hardware", nullable=True)
        )
        batch_op.add_column(sa.Column("service_id", sa.Integer(), nullable=True))

    # services.docker_labels
    op.add_column(
        "services",
        sa.Column("docker_labels", sa.Text(), nullable=True),
    )

    # app_settings.self_cluster_enabled
    op.add_column(
        "app_settings",
        sa.Column("self_cluster_enabled", sa.Boolean(), server_default="0", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "self_cluster_enabled")
    op.drop_column("services", "docker_labels")

    with op.batch_alter_table("hardware_cluster_members", recreate="auto") as batch_op:
        batch_op.drop_column("service_id")
        batch_op.drop_column("member_type")
        batch_op.alter_column("hardware_id", existing_type=sa.Integer(), nullable=False)

    op.drop_column("hardware_clusters", "type")
