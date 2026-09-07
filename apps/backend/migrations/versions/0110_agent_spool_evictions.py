"""Record permanently destroyed agent history, and the frames this server refused.

Revision ID: 0110_agent_spool_evictions
Revises: 0109_discovery_enrichment
Create Date: 2026-09-06

The agent's disk spool is capped (``spool.DefaultCapBytes``, 64 MiB). When a long
outage fills it, the oldest buffered observations are deleted to make room. That
policy is deliberate — recent observations matter more than old ones — but until
now it ran *silently*: no counter, no log line, no event. The only externally
visible symptom was that the reported spool depth stopped rising, which is
indistinguishable from a backlog that drained.

These columns are the server's half of making that loud. ``spool_evicted_*`` is
what the agent reports it destroyed, and ``refused_frames`` is the same fact
about this server: several ingest paths drop a data frame outright and record
only a rate-limited-to-one-per-minute event, so the audit trail undercounts by
design. The counter does not undercount.

Column groups, and why they are in one migration:

* ``spool_evicted_frames`` / ``spool_evicted_bytes`` / ``spool_evicted_oldest_at``
  / ``spool_evicted_newest_at`` / ``spool_evicted_reported_at`` — the agent's
  cumulative eviction record and the window of observations it covers.
* ``refused_frames`` / ``refused_frames_last_at`` / ``refused_frames_last_reason``
  — this server's own count of data frames it dropped for a given agent.
* ``data_ack_negotiated`` — reserved for the delivery-acknowledgement handshake a
  later phase adds. It is declared here rather than in a migration of its own so
  that these agent columns land in one step for a self-hoster upgrading on their
  own schedule; it stays unread until that phase wires it.

Every column is nullable and **nothing is backfilled**. NULL means "never
reported", which is the truth for an agent whose build predates the fields, and
it stays deliberately distinct from 0 ("reported, and nothing was destroyed").
Writing a 0 here would claim a report that never happened — the same distinction
``0097_agent_spool_state`` documents for the backlog columns, enforced the same
way: the wire payloads carry no ``omitempty`` and the server gates persistence on
key presence.

Every step inspects first, so replaying it is safe. ``agents`` is a plain table
(not a hypertable), so no TimescaleDB guard is needed here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0110_agent_spool_evictions"
down_revision = "0109_discovery_enrichment"
branch_labels = None
depends_on = None

_TABLE = "agents"
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("spool_evicted_frames", sa.Integer()),
    ("spool_evicted_bytes", sa.BigInteger()),
    ("spool_evicted_oldest_at", sa.DateTime(timezone=True)),
    ("spool_evicted_newest_at", sa.DateTime(timezone=True)),
    ("spool_evicted_reported_at", sa.DateTime(timezone=True)),
    ("refused_frames", sa.Integer()),
    ("refused_frames_last_at", sa.DateTime(timezone=True)),
    ("refused_frames_last_reason", sa.String(length=64)),
    ("data_ack_negotiated", sa.Boolean()),
)


def upgrade() -> None:
    """Add the eviction, refusal and delivery-ack columns, if they are absent."""
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """Drop the columns this revision added, if they are present."""
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    for name, _type in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
