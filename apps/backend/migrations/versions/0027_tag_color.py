"""add tag color column

Revision ID: 0027_tag_color
Revises: 0026_pg_jsonb_teams_topologies
Create Date: 2026-03-09

"""

import sqlalchemy as sa
from alembic import op

revision = "0027_tag_color"
down_revision = "0026_pg_jsonb_teams_topologies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tags", sa.Column("color", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tags", "color")
