"""Add audit log hashes for non-repudiation

Revision ID: a3b4c5d6e7f9
Revises: a3b4c5d6e7f8
Create Date: 2026-03-07 18:50:00.000000
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def get_dialect() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if not insp.has_table("logs"):
        return

    log_cols = {c["name"] for c in insp.get_columns("logs")}

    if "previous_hash" not in log_cols:
        op.add_column("logs", sa.Column("previous_hash", sa.String(), nullable=True))
    if "log_hash" not in log_cols:
        op.add_column("logs", sa.Column("log_hash", sa.String(), nullable=True))

    # Create index on log_hash (guard against already existing)
    existing_indexes = {idx["name"] for idx in insp.get_indexes("logs")}
    if "ix_logs_log_hash" not in existing_indexes:
        with op.batch_alter_table("logs") as batch_op:
            batch_op.create_index(batch_op.f("ix_logs_log_hash"), ["log_hash"], unique=True)

    # Backfill missing hashes sequence — requires all source columns to be present.
    required_for_backfill = {
        "id",
        "timestamp",
        "action",
        "actor_id",
        "role_at_time",
        "entity_type",
        "entity_id",
        "diff",
        "ip_address",
    }
    # Re-read columns after any additions above.
    log_cols = {c["name"] for c in insp.get_columns("logs")}
    if not required_for_backfill.issubset(log_cols):
        return

    logs = conn.execute(
        sa.text(
            "SELECT id, timestamp, action, actor_id, role_at_time, "
            "entity_type, entity_id, diff, ip_address FROM logs ORDER BY id ASC"
        )
    ).fetchall()

    previous_hash = None
    for row in logs:
        # Convert timestamp to string manually if needed or just use ISO format
        # The app uses _now_iso or utcnow_iso, which is basically an ISO timestamp
        # row[1] is typically a datetime object
        ts = row[1]
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        entry_data = {
            "timestamp": ts_iso,
            "action": row[2],
            "actor_id": row[3],
            "role_at_time": row[4],
            "entity_type": row[5],
            "entity_id": row[6],
            "diff": row[7],
            "ip_address": row[8],
            "previous_hash": previous_hash,
        }
        payload = json.dumps(entry_data, sort_keys=True)
        current_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # Update log row
        conn.execute(
            sa.text("UPDATE logs SET previous_hash = :ph, log_hash = :lh WHERE id = :log_id"),
            {"ph": previous_hash, "lh": current_hash, "log_id": row[0]},
        )
        previous_hash = current_hash


def downgrade() -> None:
    with op.batch_alter_table("logs") as batch_op:
        batch_op.drop_index(batch_op.f("ix_logs_log_hash"))
    op.drop_column("logs", "log_hash")
    op.drop_column("logs", "previous_hash")
