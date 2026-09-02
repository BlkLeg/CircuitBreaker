"""agent TLS trust rotation: successor policy + per-agent convergence

Revision ID: 0107_agent_tls_pin_rotation
Revises: 0106_failed_messages
Create Date: 2026-09-01

Route F4. The agent's tls_pin was loaded once from agent.toml and never
written again, so regenerating a self-signed certificate — or switching
between self-signed and Let's Encrypt in either direction — stranded every
enrolled agent on all four of its dial paths, including the update download
that would otherwise be how a broken agent is repaired.

Purely additive: six nullable columns across two existing tables, all
defaulting to NULL, which reads as "no rotation in progress" and "no
convergence observed". A deployment that has not run this migration is
unaffected, and nothing reads these columns except the rotation surface added
alongside them.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0107_agent_tls_pin_rotation"
down_revision: str | Sequence[str] | None = "0106_failed_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # IF NOT EXISTS throughout: a self-hoster may upgrade from any prior
    # version on their own schedule, and a half-updated deployment that has
    # already picked some of these up must not fail the whole migration.
    op.execute(
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS agent_tls_pin_successor_mode VARCHAR"
    )
    op.execute("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS agent_tls_pin_successor TEXT")
    op.execute(
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS "
        "agent_tls_pin_rotation_started_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS "
        "agent_tls_pin_rotation_overlap_expires_at TIMESTAMPTZ"
    )
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS tls_pin_current_pinned_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tls_pin_successor_pinned_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "tls_pin_successor_pinned_at")
    op.drop_column("agents", "tls_pin_current_pinned_at")
    op.drop_column("app_settings", "agent_tls_pin_rotation_overlap_expires_at")
    op.drop_column("app_settings", "agent_tls_pin_rotation_started_at")
    op.drop_column("app_settings", "agent_tls_pin_successor")
    op.drop_column("app_settings", "agent_tls_pin_successor_mode")
