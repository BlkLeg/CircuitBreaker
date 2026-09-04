"""agent TLS trust rotation: which successor an agent actually holds

Revision ID: 0108_agent_tls_pin_fp
Revises: 0107_agent_tls_pin_rotation
Create Date: 2026-09-03

Slice 4.1 follow-up (H5). `tls_pin_successor_pinned_at` records *that* an agent
reported holding a successor policy, never *which* one. An agent can hold a
permanently stale successor — the runbook's own abandon procedure clears the
server state and no frame ever tells agents to drop theirs, and the agent never
enforces the successor's expiry — so on the next rotation its heartbeat marks it
converged for a policy it has never seen. The gate opens and the cutover strands
it.

One nullable column: the fingerprint of the policy the agent says it holds,
compared against the advertised one before convergence is credited. NULL is the
honest answer for an agent predating the field, and it counts as unconverged —
which is the safe direction, since it blocks a cutover rather than permitting
one that would strand the fleet.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0108_agent_tls_pin_fp"
down_revision: str | Sequence[str] | None = "0107_agent_tls_pin_rotation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # IF NOT EXISTS, for the same reason 0107 gives: a self-hoster upgrades on
    # their own schedule and a half-updated deployment must still work.
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS tls_pin_successor_fingerprint VARCHAR(32)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agents", "tls_pin_successor_fingerprint")
