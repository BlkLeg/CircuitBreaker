"""Add the remote-probe vantage columns and the probe-run lease table.

Revision ID: 0099_monitor_probe_runs
Revises: 0098_agent_networks
Create Date: 2026-08-07

Task 6 / §1. A monitor picks exactly one vantage — the server
(``probe_agent_id IS NULL``, every monitor that exists today) or one named
agent — and each remote check gets a durable lease row so a silent agent is a
recoverable state rather than a wedged monitor.

Both objects are in ``0001_init``'s exclusion lists, so this revision is what
creates them on a fresh install as well as on an upgrade — the same shape
``0089_agents.py`` and ``0098_agent_networks.py`` use, and for the same reason
in two different flavours. ``monitor_items.probe_agent_id`` points at
``agents``, an excluded *table*, so the bootstrap's ``_should_copy_fk`` would
drop the constraint and emit a bare integer, voiding the RESTRICT lifecycle
below. ``monitor_probe_runs``' index-copy would drop ``postgresql_where`` and
turn the partial unique index into a full one, capping a fresh install at one
probe run per monitor forever.

Every step inspects first, so replaying is safe. Nothing is backfilled:
``probe_execution_status`` stays NULL for a server-executed monitor, which is
how "this monitor has no vantage condition" is told apart from "its vantage is
ready".
"""

from __future__ import annotations

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "0099_monitor_probe_runs"
down_revision = "0098_agent_networks"
branch_labels = None
depends_on = None

_ITEMS = "monitor_items"
_RUNS = "monitor_probe_runs"
_ITEMS_INDEX = "ix_monitor_items_probe_due"
_ACTIVE_RUN_INDEX = "uq_monitor_probe_runs_active"
# Ordered so the downgrade can drop them back to front. Each entry builds a
# fresh `sa.Column` because a `ForeignKey` object binds to exactly one column
# and this migration is replayed (idempotently) rather than run once.
_ITEM_COLUMNS: tuple[tuple[str, Callable[[], sa.Column]], ...] = (
    (
        "probe_agent_id",
        lambda: sa.Column(
            "probe_agent_id",
            sa.Integer(),
            sa.ForeignKey(
                "agents.id",
                ondelete="RESTRICT",
                name="fk_monitor_items_probe_agent_id_agents",
            ),
            nullable=True,
        ),
    ),
    (
        "probe_execution_status",
        lambda: sa.Column("probe_execution_status", sa.String(16), nullable=True),
    ),
    (
        "probe_execution_reason",
        lambda: sa.Column("probe_execution_reason", sa.String(128), nullable=True),
    ),
    (
        "probe_last_dispatched_at",
        lambda: sa.Column("probe_last_dispatched_at", sa.DateTime(timezone=True), nullable=True),
    ),
    (
        "probe_last_result_at",
        lambda: sa.Column("probe_last_result_at", sa.DateTime(timezone=True), nullable=True),
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())

    if _ITEMS in tables:
        existing = {column["name"] for column in inspector.get_columns(_ITEMS)}
        for name, build_column in _ITEM_COLUMNS:
            if name not in existing:
                op.add_column(_ITEMS, build_column())
        if _ITEMS_INDEX not in {index["name"] for index in inspector.get_indexes(_ITEMS)}:
            op.create_index(_ITEMS_INDEX, _ITEMS, ["probe_agent_id", "enabled", "next_due_at"])

    if _RUNS not in tables:
        op.create_table(
            _RUNS,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(32), nullable=False),
            sa.Column("monitor_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("outcome", sa.String(16), nullable=True),
            sa.Column("msg", sa.String(2000), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("result_metadata", JSONB(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["monitor_id"],
                ["monitor_items.id"],
                name="fk_monitor_probe_runs_monitor_id_monitor_items",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["agent_id"],
                ["agents.id"],
                name="fk_monitor_probe_runs_agent_id_agents",
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_monitor_probe_runs_run_id", _RUNS, ["run_id"], unique=True)
        op.create_index(
            "ix_monitor_probe_runs_agent_status", _RUNS, ["agent_id", "status", "scheduled_at"]
        )
        op.create_index("ix_monitor_probe_runs_monitor_time", _RUNS, ["monitor_id", "created_at"])
        # Partial, so completed history accumulates freely while only one run
        # per monitor may be in flight. Declared here *and* on the model so the
        # bootstrap-free fresh install and `create_all` agree.
        op.create_index(
            _ACTIVE_RUN_INDEX,
            _RUNS,
            ["monitor_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'dispatched')"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())

    if _RUNS in tables:
        op.drop_table(_RUNS)

    if _ITEMS in tables:
        if _ITEMS_INDEX in {index["name"] for index in inspector.get_indexes(_ITEMS)}:
            op.drop_index(_ITEMS_INDEX, table_name=_ITEMS)
        existing = {column["name"] for column in inspector.get_columns(_ITEMS)}
        for name, _build_column in reversed(_ITEM_COLUMNS):
            if name in existing:
                op.drop_column(_ITEMS, name)
