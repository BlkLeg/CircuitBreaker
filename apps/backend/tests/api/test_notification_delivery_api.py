"""The Test endpoint reports safe shared delivery dispositions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import NotificationRoute, NotificationSink
from app.services.notification_secrets import encrypt_config


@pytest.mark.asyncio
async def test_webhook_redirect_is_not_reported_as_success(
    client, auth_headers, db_session, app_cfg
) -> None:
    sink = NotificationSink(
        name="Redirecting Slack",
        provider_type="slack",
        provider_config=encrypt_config(
            "slack", {"webhook_url": "https://hooks.slack.com/services/A/B/C"}
        ),
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    response = SimpleNamespace(
        status_code=302,
        headers={"Location": "http://internal.example/secret"},
        text="provider-body-must-not-leak",
    )

    with patch(
        "app.api.notifications.safe_async_request",
        AsyncMock(return_value=response),
    ) as sent:
        result = await client.post(
            f"/api/v1/notifications/sinks/{sink.id}/test", headers=auth_headers
        )

    assert result.status_code == 200
    body = result.json()
    assert body["ok"] is False
    assert body["state"] == "terminal"
    assert body["reason_code"] == "redirect_rejected"
    assert "provider-body-must-not-leak" not in result.text
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_deleting_a_destination_removes_its_routes(
    client, auth_headers, db_session, app_cfg
) -> None:
    sink = NotificationSink(
        name="Retired Slack",
        provider_type="slack",
        provider_config=encrypt_config(
            "slack", {"webhook_url": "https://hooks.slack.com/services/A/B/C"}
        ),
        enabled=True,
    )
    db_session.add(sink)
    db_session.flush()
    db_session.add(NotificationRoute(sink_id=sink.id, alert_severity="warning", enabled=True))
    db_session.commit()
    sink_id = sink.id

    result = await client.delete(f"/api/v1/notifications/sinks/{sink_id}", headers=auth_headers)

    assert result.status_code == 200
    assert (
        db_session.query(NotificationRoute).filter(NotificationRoute.sink_id == sink_id).count()
        == 0
    )


@pytest.mark.asyncio
async def test_webhook_500_exhausts_into_a_visible_failed_test(
    client, auth_headers, db_session, app_cfg, monkeypatch
) -> None:
    from app.services import notification_delivery

    sink = NotificationSink(
        name="Unavailable Slack",
        provider_type="slack",
        provider_config=encrypt_config(
            "slack", {"webhook_url": "https://hooks.slack.com/services/A/B/C"}
        ),
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    response = SimpleNamespace(status_code=500, headers={}, text="private body")
    request = AsyncMock(return_value=response)
    policy_type = notification_delivery.DeliveryPolicy
    monkeypatch.setattr(
        notification_delivery,
        "DeliveryPolicy",
        lambda: policy_type(max_attempts=2, base_delay_seconds=0),
    )

    with patch("app.api.notifications.safe_async_request", request):
        result = await client.post(
            f"/api/v1/notifications/sinks/{sink.id}/test", headers=auth_headers
        )

    body = result.json()
    assert body["ok"] is False
    assert body["state"] == "terminal"
    assert body["reason_code"] == "retry_exhausted"
    assert body["attempt_count"] == 2
    assert "private body" not in result.text
    assert request.await_count == 2
