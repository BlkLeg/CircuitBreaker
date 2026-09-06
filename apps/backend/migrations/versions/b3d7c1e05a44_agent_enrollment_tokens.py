"""Add agent_enrollment_tokens and agents.enrollment_token_id.

Revision ID: b3d7c1e05a44
Revises: a191f689a082
Create Date: 2026-09-06

Slice B: unattended enrollment. Both statements are existence-guarded because a
self-hoster upgrades on their own schedule and a half-updated deployment must
still work — see CLAUDE.md's backward-compatibility rule.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7c1e05a44"
down_revision: str | None = "a191f689a082"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the token table and the agent's provenance column."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS agent_enrollment_tokens (
                id SERIAL PRIMARY KEY,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                label VARCHAR NOT NULL,
                endpoint_url VARCHAR NOT NULL,
                capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
                max_uses INTEGER NOT NULL DEFAULT 1,
                uses INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ,
                created_by_user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_enrollment_tokens_token_hash "
            "ON agent_enrollment_tokens (token_hash)"
        )
    )
    bind.execute(
        sa.text(
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS enrollment_token_id INTEGER "
            "REFERENCES agent_enrollment_tokens(id)"
        )
    )


def downgrade() -> None:
    """Drop the column, then the table it references."""
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS enrollment_token_id"))
    bind.execute(sa.text("DROP TABLE IF EXISTS agent_enrollment_tokens"))
