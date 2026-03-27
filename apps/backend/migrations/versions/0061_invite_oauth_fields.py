"""Add accepted_at to user_invites and invite_token to oauth_states."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0061_invite_oauth_fields"
down_revision = "0060_hardware_mounting_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)

    if "accepted_at" not in {c["name"] for c in insp.get_columns("user_invites")}:
        op.add_column(
            "user_invites",
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "invite_token" not in {c["name"] for c in insp.get_columns("oauth_states")}:
        op.add_column(
            "oauth_states",
            sa.Column("invite_token", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user_invites", "accepted_at")
    op.drop_column("oauth_states", "invite_token")
