"""Per-sink receipts prevent successful destinations from being resent."""

from types import SimpleNamespace

import pytest

from app.db.models import NotificationDelivery, NotificationRoute, NotificationSink
from app.schemas.notifications import AlertEnvelope
from app.services.notification_routing import stable_event_id
from app.services.notification_secrets import encrypt_config
from tests.services.notification_worker_harness import FakeMsg, attach_worker_session

_GOOD_URL = "https://hooks.slack.com/services/GOOD/GOOD/GOOD"
_FLAKY_URL = "https://hooks.slack.com/services/FLAKY/FLAKY/FLAKY"


def _add_slack_route(db_session, name: str, url: str, *, enabled: bool = True) -> int:
    sink = NotificationSink(
        name=name,
        provider_type="slack",
        provider_config=encrypt_config("slack", {"webhook_url": url}),
        enabled=enabled,
    )
    db_session.add(sink)
    db_session.flush()
    db_session.add(NotificationRoute(sink_id=sink.id, alert_severity="*", enabled=True))
    db_session.commit()
    return sink.id


@pytest.mark.asyncio
async def test_redelivery_retries_only_the_outstanding_sink(
    monkeypatch, db_session, app_cfg
) -> None:
    from app.workers import notification_worker

    attach_worker_session(monkeypatch, db_session)
    good_id = _add_slack_route(db_session, "Good", _GOOD_URL)
    flaky_id = _add_slack_route(db_session, "Flaky", _FLAKY_URL)
    monkeypatch.setattr(notification_worker, "_NOTIFICATION_RETRIES", 0)
    calls: list[str] = []
    flaky_accepted = False

    async def send(config, _title, _message, _severity):
        nonlocal flaky_accepted
        url = config["webhook_url"]
        calls.append(url)
        status = 200 if url == _GOOD_URL or flaky_accepted else 500
        return SimpleNamespace(status_code=status, headers={})

    monkeypatch.setattr(notification_worker, "notify_slack", send)
    msg = FakeMsg(
        "alert.monitor.down",
        {"severity": "critical", "title": "Host down", "message": "db01"},
    )

    with pytest.raises(notification_worker.RetryableNotificationError):
        await notification_worker.process_alert(msg)

    first = {row.sink_id: row.state for row in db_session.query(NotificationDelivery).all()}
    assert first == {good_id: "accepted", flaky_id: "retryable"}

    flaky_accepted = True
    await notification_worker.process_alert(msg)

    assert calls.count(_GOOD_URL) == 1
    assert calls.count(_FLAKY_URL) == 2
    assert {row.sink_id: row.state for row in db_session.query(NotificationDelivery).all()} == {
        good_id: "accepted",
        flaky_id: "accepted",
    }


@pytest.mark.asyncio
async def test_disabled_sink_records_no_route_without_sending(
    monkeypatch, db_session, app_cfg
) -> None:
    from app.workers import notification_worker

    attach_worker_session(monkeypatch, db_session)
    _add_slack_route(db_session, "Disabled", _GOOD_URL, enabled=False)

    async def must_not_send(*_args):
        raise AssertionError("disabled destination was sent")

    monkeypatch.setattr(notification_worker, "notify_slack", must_not_send)
    await notification_worker.process_alert(
        FakeMsg("alert.monitor.down", {"severity": "critical", "title": "Host down"})
    )

    receipt = db_session.query(NotificationDelivery).one()
    assert receipt.sink_key == 0
    assert receipt.state == "terminal"
    assert receipt.reason_code == "no_route"


@pytest.mark.asyncio
async def test_invalid_alert_payload_propagates_to_consumer_failure(
    monkeypatch, db_session, app_cfg
) -> None:
    from app.workers import notification_worker

    attach_worker_session(monkeypatch, db_session)
    msg = SimpleNamespace(subject="alert.bad", data=b"{not-json")

    with pytest.raises(
        notification_worker.InvalidAlertError,
        match="invalid and cannot be delivered",
    ):
        await notification_worker.process_alert(msg)


def test_stream_sequence_is_preferred_over_payload_hash() -> None:
    msg = SimpleNamespace(
        subject="alert.monitor.down",
        data=b'{"title":"same"}',
        headers={},
        metadata=SimpleNamespace(stream="CB_EVENTS", sequence=SimpleNamespace(stream=417)),
    )

    assert stable_event_id(msg, AlertEnvelope(title="same")) == "js:CB_EVENTS:417"
