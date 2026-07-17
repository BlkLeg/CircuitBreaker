"""add_scan_progress_style

Revision ID: abec47e19d13
Revises: 0084_lan_discovery_desired_setting
Create Date: 2026-07-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abec47e19d13"
down_revision: str | Sequence[str] | None = "0084_lan_discovery_desired_setting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "app_settings",
        sa.Column("scan_progress_style", sa.String(), server_default="circuit", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("app_settings", "scan_progress_style")
