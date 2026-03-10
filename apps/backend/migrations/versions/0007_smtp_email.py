"""SMTP email delivery — AppSettings SMTP config + UserInvite email tracking

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-03-07 18:00:00.000000

Adds to app_settings:
  smtp_enabled, smtp_host, smtp_port, smtp_username, smtp_password_enc,
  smtp_from_email, smtp_from_name, smtp_tls,
  smtp_last_test_at, smtp_last_test_status

Adds to user_invites:
  email_sent_at, email_status, email_error
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    app_cols = {c["name"] for c in inspector.get_columns("app_settings")}
    invite_cols = {c["name"] for c in inspector.get_columns("user_invites")}

    # ── app_settings SMTP columns ────────────────────────────────────────────
    if "smtp_enabled" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("smtp_enabled", sa.Boolean(), nullable=False, server_default="0"),
        )
    if "smtp_host" not in app_cols:
        op.add_column(
            "app_settings", sa.Column("smtp_host", sa.String(), nullable=False, server_default="")
        )
    if "smtp_port" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        )
    if "smtp_username" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("smtp_username", sa.String(), nullable=False, server_default=""),
        )
    if "smtp_password_enc" not in app_cols:
        op.add_column("app_settings", sa.Column("smtp_password_enc", sa.Text(), nullable=True))
    if "smtp_from_email" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("smtp_from_email", sa.String(), nullable=False, server_default=""),
        )
    if "smtp_from_name" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "smtp_from_name", sa.String(), nullable=False, server_default="Circuit Breaker"
            ),
        )
    if "smtp_tls" not in app_cols:
        op.add_column(
            "app_settings", sa.Column("smtp_tls", sa.Boolean(), nullable=False, server_default="1")
        )
    if "smtp_last_test_at" not in app_cols:
        op.add_column("app_settings", sa.Column("smtp_last_test_at", sa.String(), nullable=True))
    if "smtp_last_test_status" not in app_cols:
        op.add_column(
            "app_settings", sa.Column("smtp_last_test_status", sa.String(), nullable=True)
        )

    # ── user_invites email tracking columns ──────────────────────────────────
    if "email_sent_at" not in invite_cols:
        op.add_column("user_invites", sa.Column("email_sent_at", sa.String(), nullable=True))
    if "email_status" not in invite_cols:
        op.add_column(
            "user_invites",
            sa.Column("email_status", sa.String(), nullable=False, server_default="not_sent"),
        )
    if "email_error" not in invite_cols:
        op.add_column("user_invites", sa.Column("email_error", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; skip for safety.
    pass
