"""Persist the agent-reported directly connected networks with a generation.

Revision ID: 0098_agent_networks
Revises: 0097_agent_spool_state
Create Date: 2026-08-07

Task 2 / D-1. `hello.networks` is the only input the slice-3 scope evaluator
has, so it needs somewhere durable to live: one current report per agent
(hence the unique constraint on `agent_id`, not a history table), carrying a
`generation` that advances only when the normalized facts differ.

`agent_networks` is in `0001_init`'s `_EXCLUDED_TABLES`, so this revision is
what creates it on a fresh install as well as on an upgrade — which is why
every step is inspect-first / `if_not_exists`, exactly as `0089_agents.py`
does for the rest of the agent tables. Nothing is backfilled: an agent whose
build predates network reporting has no row until it reconnects and says so,
and an invented empty report would read as "this agent is attached to no
networks" — a scope of nothing rather than a scope not yet known.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0098_agent_networks"
down_revision = "0097_agent_spool_state"
branch_labels = None
depends_on = None

_TABLE = "agent_networks"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("facts", JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("agent_id", name="uq_agent_networks_agent_id"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table(_TABLE, if_exists=True)
