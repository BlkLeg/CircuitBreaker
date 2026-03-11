"""Add onboarding table for OOBE step state (Homarr-style resume).

Revision ID: 0032_onboarding
Revises: 0031_graph_uplink_overrides
Create Date: 2026-03-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_onboarding"
down_revision = "0031_graph_uplink_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(), nullable=False, server_default="start"),
        sa.Column("previous_step", sa.String(), nullable=False, server_default="start"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO onboarding (id, step, previous_step, updated_at) "
        "VALUES (1, 'start', 'start', CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_table("onboarding")
