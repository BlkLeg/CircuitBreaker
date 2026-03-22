"""Add slug column to integrations table.

Revision ID: 0052_add_slug_to_integrations
Revises: 0051_integrations
Create Date: 2026-03-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_add_slug_to_integrations"
down_revision = "0051_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("slug", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integrations", "slug")
