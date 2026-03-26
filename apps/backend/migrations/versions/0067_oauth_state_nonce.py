"""Add nonce column to oauth_states for OIDC replay protection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0067_oauth_state_nonce"
down_revision = "0066_ipam_notes_network_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_states", sa.Column("nonce", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_states", "nonce")
