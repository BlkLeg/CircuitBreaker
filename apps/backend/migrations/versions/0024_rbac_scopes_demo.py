"""add user scopes and demo expiry

Revision ID: 0024_rbac_scopes_demo
Revises: 0023_webhook_v1_fields
Create Date: 2026-03-08

"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0024_rbac_scopes_demo"
down_revision = "0023_webhook_v1_fields"
branch_labels = None
depends_on = None


_EDITOR_DEFAULT_SCOPES = [
    "read:*",
    "write:hardware",
    "write:services",
    "write:networks",
    "write:clusters",
    "write:external",
    "write:docs",
    "write:graph",
    "write:layout",
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("users"):
        return

    user_cols = {c["name"] for c in insp.get_columns("users")}

    # Guard: 0006 may have been skipped on old DBs stamped to 0015.
    # Add role column with the same definition used in 0006 so the backfill below works.
    if "role" not in user_cols:
        op.add_column(
            "users",
            sa.Column("role", sa.String(), nullable=False, server_default="viewer"),
        )
        user_cols.add("role")

    if "scopes" not in user_cols:
        op.add_column("users", sa.Column("scopes", sa.Text(), nullable=False, server_default="[]"))
        user_cols.add("scopes")
    if "demo_expires" not in user_cols:
        op.add_column("users", sa.Column("demo_expires", sa.DateTime(timezone=True), nullable=True))

    if insp.has_table("user_invites"):
        invite_cols = {c["name"] for c in insp.get_columns("user_invites")}
        if "scopes" not in invite_cols:
            op.add_column("user_invites", sa.Column("scopes", sa.Text(), nullable=True))

    if not {"id", "role", "scopes"}.issubset(user_cols):
        return

    rows = bind.execute(sa.text("SELECT id, role, scopes FROM users")).fetchall()
    for row in rows:
        current = row[2]
        if current and str(current).strip() not in ("", "[]", "{}"):
            continue
        role = (row[1] or "").strip().lower()
        if role == "admin":
            scopes = ["read:*", "write:*", "delete:*", "admin:*"]
        elif role == "viewer":
            scopes = ["read:*"]
        else:
            if role == "":
                bind.execute(
                    sa.text("UPDATE users SET role = 'editor' WHERE id = :id"), {"id": row[0]}
                )
            scopes = _EDITOR_DEFAULT_SCOPES
        bind.execute(
            sa.text("UPDATE users SET scopes = :scopes WHERE id = :id"),
            {"id": row[0], "scopes": json.dumps(scopes)},
        )


def downgrade() -> None:
    op.drop_column("user_invites", "scopes")
    op.drop_column("users", "demo_expires")
    op.drop_column("users", "scopes")
