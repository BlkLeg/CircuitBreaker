"""``process_alert`` honours a route's threshold, not an exact match (INC-03).

The dispatcher compared ``route.alert_severity == severity``, so an operator who
set a route to "Minimum Severity: Info" received info alerts and never saw the
warning or critical ones — the opposite of the label, failing in the dangerous
direction. These tests pin the routing decision at the worker, where the drop
actually happened.
"""

from unittest.mock import AsyncMock

import pytest

from tests.services.notification_worker_harness import (
    FakeMsg,
    attach_worker_session,
    routed_slack_sink,
)

_ALERT_SUBJECT = "alert.monitor.down"


@pytest.fixture
def worker_db(monkeypatch, db_session, app_cfg):
    return attach_worker_session(monkeypatch, db_session)


async def _deliveries_for(monkeypatch, severity: str) -> AsyncMock:
    from app.workers import notification_worker

    sent = AsyncMock()
    monkeypatch.setattr(notification_worker, "notify_slack", sent)
    await notification_worker.process_alert(
        FakeMsg(_ALERT_SUBJECT, {"severity": severity, "title": "Host down"})
    )
    return sent


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", ["info", "warning", "critical"])
async def test_an_info_route_receives_warning_and_critical_too(
    worker_db, monkeypatch, severity: str
) -> None:
    routed_slack_sink(worker_db, alert_severity="info")

    sent = await _deliveries_for(monkeypatch, severity)

    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_warning_route_still_drops_info(worker_db, monkeypatch) -> None:
    routed_slack_sink(worker_db, alert_severity="warning")

    sent = await _deliveries_for(monkeypatch, "info")

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_critical_route_receives_critical_only(worker_db, monkeypatch) -> None:
    routed_slack_sink(worker_db, alert_severity="critical")

    assert (await _deliveries_for(monkeypatch, "warning")).await_count == 0
    assert (await _deliveries_for(monkeypatch, "critical")).await_count == 1


@pytest.mark.asyncio
async def test_a_disabled_route_receives_nothing_however_urgent(worker_db, monkeypatch) -> None:
    """The threshold widens what a route accepts; it must not revive a disabled one."""
    routed_slack_sink(worker_db, alert_severity="info", route_enabled=False)

    sent = await _deliveries_for(monkeypatch, "critical")

    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unrecognised_severity_reaches_even_a_critical_only_route(
    worker_db, monkeypatch
) -> None:
    """An alert whose urgency cannot be read is delivered, not silently dropped."""
    routed_slack_sink(worker_db, alert_severity="critical")

    sent = await _deliveries_for(monkeypatch, "meltdown")

    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_sink_selected_by_two_routes_is_delivered_to_once(worker_db, monkeypatch) -> None:
    """The workaround for this bug must not become a double-notification bug.

    Operators who hit INC-03 worked around it by adding one route per severity
    to the same sink. Under threshold matching both of those routes now select a
    critical alert, and ``_is_duplicate`` keys on the alert, not on the sink — so
    without deduplication the fix would post to that channel twice.
    """
    from app.db.models import NotificationRoute

    sink = routed_slack_sink(worker_db, alert_severity="info")
    worker_db.add(NotificationRoute(sink_id=sink.id, alert_severity="warning", enabled=True))
    worker_db.commit()

    sent = await _deliveries_for(monkeypatch, "critical")

    sent.assert_awaited_once()
