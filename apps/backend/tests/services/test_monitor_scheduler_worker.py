# apps/backend/tests/services/test_monitor_scheduler_worker.py
import asyncio
from datetime import UTC, datetime, timedelta

from app.db.models import MonitorItem
from app.workers.monitor_scheduler import tick


def test_tick_publishes_due_items(db_session):
    item = MonitorItem(
        target_type="ip",
        target_id=None,
        host="10.0.0.9",
        check_type="icmp",
        params={},
        interval_secs=60,
        enabled=True,
        next_due_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    db_session.add(item)
    db_session.commit()

    published: list[tuple[str, dict]] = []

    async def fake_publish(subject, payload):
        published.append((subject, payload))
        return True

    # Pass a factory that returns the test's savepoint-isolated session
    # so tick() sees the item we just committed.
    n = asyncio.run(tick(lambda: db_session, fake_publish))
    assert n == 1
    assert published[0][0] == "mon.poll.item"
    assert published[0][1]["host"] == "10.0.0.9"
