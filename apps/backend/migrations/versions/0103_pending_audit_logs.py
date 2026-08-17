"""Durable spool for audit entries that could not be hash-chained in time.

Revision ID: 0103_pending_audit_logs
Revises: 0102_bootstrap_setup_token
Create Date: 2026-08-15

Appending to `logs` means reading the chain tail and writing the next link
under the audit-chain advisory lock. A background writer that cannot take that
lock within its deadline used to discard the entry, which loses the record of
an action that really happened. It now lands here instead, and
services/audit_spool.drain links it into the chain once the lock is free.

The table carries no hash and no link to its neighbours on purpose: that is
what makes the insert an ordinary uncontended INSERT, which is the whole point
of having somewhere to put an entry that could not be chained.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "0103_pending_audit_logs"
down_revision = "0102_bootstrap_setup_token"
branch_labels = None
depends_on = None

_TABLE = "pending_audit_logs"


def _tables() -> set[str]:
    return set(sa_inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # Existence-guarded like every other migration here: 0001_init bootstraps
    # fresh databases from the current Base.metadata, which already contains
    # this table, so on a fresh install there is nothing left to create.
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("deferred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
    )
    # Drains take the oldest first, and spool age is what an operator alarms
    # on, so both reads are ordered by this column.
    op.create_index(f"ix_{_TABLE}_deferred_at", _TABLE, ["deferred_at"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    # Anything still spooled has not been chained yet, so dropping the table
    # destroys audit records. Downgrading is only safe once drain() has run.
    op.drop_index(f"ix_{_TABLE}_deferred_at", table_name=_TABLE)
    op.drop_table(_TABLE)
