"""Backfill monitor_items from existing hardware_monitors."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

revision = "0083_migrate_hardware_monitors"
down_revision = "0082_telemetry_item_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.services.monitoring.backfill import backfill_monitor_items

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        n = backfill_monitor_items(session)
        session.commit()
        print(f"[0083] backfilled {n} monitor_items from hardware_monitors")
    finally:
        session.close()


def downgrade() -> None:
    # Backfilled rows are left in place; monitor_items itself is dropped by 0081 downgrade.
    pass
