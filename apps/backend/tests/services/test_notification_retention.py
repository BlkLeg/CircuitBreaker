"""Receipt cleanup stays beyond stream replay and preserves retryable work."""

from datetime import UTC, datetime, timedelta

from app.db.models import NotificationDelivery
from app.services.notification_retention import (
    notification_receipt_retention_days,
    purge_notification_delivery_receipts,
)


def _receipt(event_id: str, state: str, updated_at: datetime) -> NotificationDelivery:
    return NotificationDelivery(
        event_id=event_id,
        sink_key=1,
        provider="slack",
        state=state,
        updated_at=updated_at,
    )


def test_retention_always_exceeds_stream_window(monkeypatch) -> None:
    monkeypatch.setenv("CB_EVENTS_RETENTION_HOURS", "72")
    monkeypatch.setenv("CB_NOTIFICATION_RECEIPT_RETENTION_DAYS", "1")

    assert notification_receipt_retention_days() == 4


def test_purge_removes_only_old_settled_receipts(db_session, monkeypatch) -> None:
    monkeypatch.setenv("CB_EVENTS_RETENTION_HOURS", "24")
    monkeypatch.setenv("CB_NOTIFICATION_RECEIPT_RETENTION_DAYS", "2")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _receipt("old-accepted", "accepted", now - timedelta(days=3)),
            _receipt("old-terminal", "terminal", now - timedelta(days=3)),
            _receipt("old-retryable", "retryable", now - timedelta(days=3)),
            _receipt("young-accepted", "accepted", now - timedelta(hours=1)),
        ]
    )
    db_session.commit()

    count = purge_notification_delivery_receipts(db_session, now=now)
    db_session.commit()

    assert count == 2
    assert {row.event_id for row in db_session.query(NotificationDelivery).all()} == {
        "old-retryable",
        "young-accepted",
    }
