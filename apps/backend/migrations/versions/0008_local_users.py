"""Local user creation — add force_password_change to users

Revision ID: d1e2f3a4b5c6
Revises: b2c3d4e5f6a7
Create Date: 2026-03-07 15:00:00.000000

Adds:
  - users: force_password_change (BOOLEAN NOT NULL DEFAULT 0)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    user_cols = {c["name"] for c in inspector.get_columns("users")}

    with op.batch_alter_table("users") as batch_op:
        if "force_password_change" not in user_cols:
            batch_op.add_column(
                sa.Column(
                    "force_password_change",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("force_password_change")
