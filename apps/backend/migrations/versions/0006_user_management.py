"""Phase 6.5 — Comprehensive User Management

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-07 12:00:00.000000

Adds:
  - users: role, invited_by, login_attempts, locked_until, masquerade_target
  - user_sessions table (JWT revocation)
  - user_invites table (invite workflow)
  - logs: session_id, role_at_time
  - app_settings: concurrent_sessions, login_lockout_attempts, login_lockout_minutes,
    invite_expiry_days, masquerade_enabled
  - idx_audit_user_time on logs(actor_id, timestamp DESC)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # ── Create user_sessions (before logs FK) ─────────────────────────────────
    # Guard: previous failed runs may have created the table without stamping the
    # revision.  Skip creation if it already exists.
    if "user_sessions" not in existing_tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("jwt_token_hash", sa.Text(), nullable=False),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # ── Create user_invites ───────────────────────────────────────────────────
    if "user_invites" not in existing_tables:
        op.create_table(
            "user_invites",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("invited_by", sa.Integer(), nullable=False),
            sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
            ),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_user_invites_token", "user_invites", ["token"], unique=True)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    log_cols = {c["name"] for c in inspector.get_columns("logs")}
    app_cols = {c["name"] for c in inspector.get_columns("app_settings")}

    # ── Extend users ─────────────────────────────────────────────────────────
    # SQLite does not support ALTER TABLE ADD CONSTRAINT; batch mode uses
    # copy-and-move to rebuild the table with the new FK constraints.
    # Column guards handle partial runs where add_column succeeded but FK failed.
    with op.batch_alter_table("users") as batch_op:
        if "role" not in user_cols:
            batch_op.add_column(
                sa.Column("role", sa.String(), nullable=False, server_default="viewer")
            )
        if "invited_by" not in user_cols:
            batch_op.add_column(sa.Column("invited_by", sa.Integer(), nullable=True))
        if "login_attempts" not in user_cols:
            batch_op.add_column(
                sa.Column("login_attempts", sa.Integer(), nullable=False, server_default="0")
            )
        if "locked_until" not in user_cols:
            batch_op.add_column(
                sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
            )
        if "masquerade_target" not in user_cols:
            batch_op.add_column(sa.Column("masquerade_target", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_users_invited_by", "users", ["invited_by"], ["id"])
        batch_op.create_foreign_key(
            "fk_users_masquerade_target", "users", ["masquerade_target"], ["id"]
        )

    # Backfill role for existing admins
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1 OR is_superuser = 1")

    # ── Extend logs ──────────────────────────────────────────────────────────
    with op.batch_alter_table("logs") as batch_op:
        if "session_id" not in log_cols:
            batch_op.add_column(sa.Column("session_id", sa.Integer(), nullable=True))
        if "role_at_time" not in log_cols:
            batch_op.add_column(sa.Column("role_at_time", sa.String(), nullable=True))
        batch_op.create_foreign_key("fk_logs_session_id", "user_sessions", ["session_id"], ["id"])

    # ── Audit index for per-user action history ───────────────────────────────
    existing_indexes = {i["name"] for i in inspector.get_indexes("logs")}
    if "ix_logs_actor_id_timestamp" not in existing_indexes:
        op.create_index(
            "ix_logs_actor_id_timestamp",
            "logs",
            ["actor_id", "timestamp"],
            unique=False,
        )

    # ── Extend app_settings ───────────────────────────────────────────────────
    if "concurrent_sessions" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("concurrent_sessions", sa.Integer(), nullable=False, server_default="5"),
        )
    if "login_lockout_attempts" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("login_lockout_attempts", sa.Integer(), nullable=False, server_default="5"),
        )
    if "login_lockout_minutes" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("login_lockout_minutes", sa.Integer(), nullable=False, server_default="15"),
        )
    if "invite_expiry_days" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("invite_expiry_days", sa.Integer(), nullable=False, server_default="7"),
        )
    if "masquerade_enabled" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column("masquerade_enabled", sa.Boolean(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    op.drop_column("app_settings", "masquerade_enabled")
    op.drop_column("app_settings", "invite_expiry_days")
    op.drop_column("app_settings", "login_lockout_minutes")
    op.drop_column("app_settings", "login_lockout_attempts")
    op.drop_column("app_settings", "concurrent_sessions")

    op.drop_index("ix_logs_actor_id_timestamp", table_name="logs")
    with op.batch_alter_table("logs") as batch_op:
        batch_op.drop_constraint("fk_logs_session_id", type_="foreignkey")
        batch_op.drop_column("role_at_time")
        batch_op.drop_column("session_id")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_masquerade_target", type_="foreignkey")
        batch_op.drop_constraint("fk_users_invited_by", type_="foreignkey")
        batch_op.drop_column("masquerade_target")
        batch_op.drop_column("locked_until")
        batch_op.drop_column("login_attempts")
        batch_op.drop_column("invited_by")
        batch_op.drop_column("role")

    op.drop_index("ix_user_invites_token", table_name="user_invites")
    op.drop_table("user_invites")
    op.drop_table("user_sessions")
