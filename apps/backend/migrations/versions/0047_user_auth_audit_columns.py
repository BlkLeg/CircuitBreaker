"""Add auth audit columns to users table.

Revision ID: 0047_user_auth_audit_columns
Revises: 0046_hardware_hostname
Create Date: 2026-03-14

Adds columns introduced by the E2E auth system:
  - last_login_ip: IP address recorded at each successful login
  - password_changed_at: timestamp of the most recent password change
  - mfa_enrolled_at: timestamp when TOTP MFA was first activated
  - password_history: JSON ring-buffer of previous bcrypt hashes (reuse prevention)

force_password_change was already present from an earlier create_all() run;
the ADD COLUMN IF NOT EXISTS guard keeps this migration idempotent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_user_auth_audit_columns"
down_revision = "0046_hardware_hostname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("users")}

    if "last_login_ip" not in existing:
        op.add_column("users", sa.Column("last_login_ip", sa.Text(), nullable=True))

    if "password_changed_at" not in existing:
        op.add_column(
            "users",
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "mfa_enrolled_at" not in existing:
        op.add_column(
            "users",
            sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "password_history" not in existing:
        op.add_column("users", sa.Column("password_history", sa.Text(), nullable=True))

    if "force_password_change" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "force_password_change",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "password_history")
    op.drop_column("users", "mfa_enrolled_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "last_login_ip")
    # force_password_change intentionally not dropped — existed before this migration
