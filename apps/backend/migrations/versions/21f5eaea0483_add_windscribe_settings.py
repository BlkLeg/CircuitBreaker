"""add_windscribe_settings

Revision ID: 21f5eaea0483
Revises: 5ed182a77737
Create Date: 2026-07-14 14:07:19.348441

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "21f5eaea0483"
down_revision: str | Sequence[str] | None = "5ed182a77737"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "app_settings",
        sa.Column("windscribe_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "windscribe_feed_refresh_hours", sa.Integer(), server_default="1", nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("app_settings", "windscribe_feed_refresh_hours")
    op.drop_column("app_settings", "windscribe_enabled")
