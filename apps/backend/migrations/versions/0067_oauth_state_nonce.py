"""Add nonce column to oauth_states for OIDC replay protection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0067_oauth_state_nonce"
down_revision = "0066_ipam_notes_network_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    if "nonce" not in {c["name"] for c in insp.get_columns("oauth_states")}:
        op.add_column("oauth_states", sa.Column("nonce", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_states", "nonce")
