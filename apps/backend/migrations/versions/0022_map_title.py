"""add map_title to app_settings

Revision ID: 0022_map_title
Revises: 0021_daily_uptime_stats
Create Date: 2026-03-08

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_map_title"
down_revision = "0021_daily_uptime_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("map_title", sa.String(), nullable=False, server_default="Topology"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "map_title")
