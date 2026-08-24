"""Route severity is validated at the boundary (INC-03).

``RouteCreate.alert_severity`` was a bare ``str``, so a typo — or a client
sending "warn" — stored a threshold the dispatcher could never match and the
route silently delivered nothing. The choices the UI offers are now the choices
the API accepts.
"""

import pytest

from app.db.models import NotificationSink
from app.services.notification_secrets import encrypt_config

_ROUTES = "/api/v1/notifications/routes"
_SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/xoxbSECRETTOKEN"


@pytest.fixture
def sink_id(db_session) -> int:
    sink = NotificationSink(
        name="Ops Slack",
        provider_type="slack",
        provider_config=encrypt_config("slack", {"webhook_url": _SLACK_URL}),
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    return sink.id


@pytest.mark.asyncio
@pytest.mark.parametrize("alert_severity", ["*", "info", "warning", "critical"])
async def test_every_severity_the_ui_offers_is_accepted(
    client, auth_headers, sink_id: int, alert_severity: str
) -> None:
    resp = await client.post(
        _ROUTES,
        json={"sink_id": sink_id, "alert_severity": alert_severity, "enabled": True},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["alert_severity"] == alert_severity


@pytest.mark.asyncio
@pytest.mark.parametrize("alert_severity", ["warn", "CRITICAL", "", "everything"])
async def test_a_severity_no_alert_can_carry_is_rejected(
    client, auth_headers, sink_id: int, alert_severity: str
) -> None:
    resp = await client.post(
        _ROUTES,
        json={"sink_id": sink_id, "alert_severity": alert_severity, "enabled": True},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


def test_the_schema_advertises_exactly_the_severities_the_dispatcher_honours() -> None:
    """Two lists, one meaning — pin them together so they cannot drift apart.

    Drifting apart *is* INC-03: the UI offered a threshold the dispatcher did
    not implement. The API schema is now the third place that names these, and
    it is the one API clients read.
    """
    from typing import get_args

    from app.api.notifications import RouteCreate
    from app.services.notification_severity import ROUTE_SEVERITIES

    assert get_args(RouteCreate.model_fields["alert_severity"].annotation) == ROUTE_SEVERITIES
