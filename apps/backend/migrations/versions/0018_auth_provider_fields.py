"""Add auth provider fields to AppSettings

Revision ID: 567cc247f83c
Revises: fecdb2050a32
Create Date: 2026-03-08 04:33:25.977547

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "567cc247f83c"
down_revision: str | Sequence[str] | None = "fecdb2050a32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ensure oauth_providers and oidc_providers exist on app_settings (idempotent)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c["name"] for c in insp.get_columns("app_settings")}

    if "oauth_providers" not in existing_cols:
        op.add_column("app_settings", sa.Column("oauth_providers", sa.Text(), nullable=True))
    if "oidc_providers" not in existing_cols:
        op.add_column("app_settings", sa.Column("oidc_providers", sa.Text(), nullable=True))
    if "session_timeout_hours" not in existing_cols:
        op.add_column(
            "app_settings", sa.Column("session_timeout_hours", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """Remove auth provider fields from app_settings."""
    op.drop_column("app_settings", "session_timeout_hours")
    op.drop_column("app_settings", "oidc_providers")
    op.drop_column("app_settings", "oauth_providers")
