"""Record the agent's reported outbound-spool backlog on the ``agents`` row.

Revision ID: 0097_agent_spool_state
Revises: 0096_drop_agent_projection_attempts
Create Date: 2026-08-06

Task 16 / D-12. The agent reports its spool depth at connect (``hello``) and
live on every 20s ``heartbeat``; the Agent Detail page renders a catch-up
indicator from these columns, which is the only user-visible evidence that the
paced catch-up drain is making progress.

All three columns are nullable and stay NULL for an agent whose build predates
spool reporting: NULL means "never reported", distinct from 0 ("reported, and
the spool is empty"). This migration deliberately backfills nothing — writing 0
would claim a report that never happened, and the empty ``{}`` heartbeat is
what the server uses to tell the two apart.

Every step inspects first, so replaying it is safe. ``agents`` is a plain table
(not a hypertable), so no TimescaleDB guard is needed here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0097_agent_spool_state"
down_revision = "0096_drop_agent_projection_attempts"
branch_labels = None
depends_on = None

_TABLE = "agents"
_COLUMNS = (
    ("spool_depth", sa.Integer()),
    ("spool_bytes", sa.BigInteger()),
    ("spool_reported_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
