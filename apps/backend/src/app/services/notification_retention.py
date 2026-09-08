"""Bounded retention for terminal notification delivery receipts."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import NotificationDelivery
from app.db.session import SessionLocal

_BATCH_SIZE = 1_000


def notification_receipt_retention_days() -> int:
    """Keep receipts beyond the configured CB_EVENTS replay window."""
    try:
        stream_hours = max(1, int(os.getenv("CB_EVENTS_RETENTION_HOURS", "24")))
    except ValueError:
        stream_hours = 24
    minimum = max(2, math.ceil(stream_hours / 24) + 1)
    try:
        configured = int(os.getenv("CB_NOTIFICATION_RECEIPT_RETENTION_DAYS", str(minimum)))
    except ValueError:
        configured = minimum
    return max(minimum, configured)


def purge_notification_delivery_receipts(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = _BATCH_SIZE,
) -> int:
    """Delete one bounded batch of accepted/terminal receipts only."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=notification_receipt_retention_days())
    ids = [
        row_id
        for (row_id,) in (
            db.query(NotificationDelivery.id)
            .filter(
                NotificationDelivery.state.in_(("accepted", "terminal")),
                NotificationDelivery.updated_at < cutoff,
            )
            .order_by(NotificationDelivery.updated_at.asc())
            .limit(max(1, min(batch_size, _BATCH_SIZE)))
            .all()
        )
    ]
    if not ids:
        return 0
    return int(
        db.query(NotificationDelivery)
        .filter(NotificationDelivery.id.in_(ids))
        .delete(synchronize_session=False)
    )


def run_notification_delivery_receipt_purge() -> None:
    """Scheduled entry point owning its transaction."""
    with SessionLocal() as db:
        purge_notification_delivery_receipts(db)
        db.commit()
