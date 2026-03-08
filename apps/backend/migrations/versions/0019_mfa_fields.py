"""Add MFA fields to users table

Revision ID: b4a9c1d2e8f0
Revises: 567cc247f83c
Create Date: 2026-03-08 12:35:00.000000

Adds mfa_enabled, totp_secret, and backup_codes to support TOTP-based
multi-factor authentication.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4a9c1d2e8f0"
down_revision: str | Sequence[str] | None = "567cc247f83c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add mfa_enabled, totp_secret, and backup_codes columns to users (idempotent)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c["name"] for c in insp.get_columns("users")}

    if "mfa_enabled" not in existing_cols:
        op.add_column(
            "users",
            sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "totp_secret" not in existing_cols:
        op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    if "backup_codes" not in existing_cols:
        op.add_column("users", sa.Column("backup_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove MFA columns from users."""
    op.drop_column("users", "backup_codes")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "mfa_enabled")
