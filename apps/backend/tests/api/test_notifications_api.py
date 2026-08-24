"""Notification sink API — secret handling at the HTTP boundary (INC-06).

The finding this file exists for: ``GET /notifications/sinks`` used to return
``provider_config`` verbatim, so anyone who could reach the surface read every
Slack/Discord/Teams webhook URL — each of which is a bearer credential for
posting into that channel. The surface is admin-only now, but redaction is the
guarantee that does not depend on the role gate holding, so it is asserted
against the role the endpoint actually serves.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import NotificationSink

_SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/xoxbSECRETTOKEN"
_SECRET_PART = "xoxbSECRETTOKEN"
_SINKS = "/api/v1/notifications/sinks"


async def _create_slack_sink(client, auth_headers, name: str = "Ops Slack") -> dict:
    resp = await client.post(
        _SINKS,
        json={
            "name": name,
            "provider_type": "slack",
            "provider_config": {"webhook_url": _SLACK_URL},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_encrypted_sink(db_session, name: str = "Ops Slack") -> NotificationSink:
    """Insert a sink the way the API stores one, without an admin login.

    Logging in twice in one test would leave the client's cookie jar holding
    the second user's CSRF cookie, so the viewer case seeds the row directly.
    """
    from app.services.notification_secrets import encrypt_config

    sink = NotificationSink(
        name=name,
        provider_type="slack",
        provider_config=encrypt_config("slack", {"webhook_url": _SLACK_URL}),
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()
    return sink


@pytest.mark.asyncio
async def test_listing_sinks_never_returns_a_usable_webhook_url(
    client, auth_headers, db_session
) -> None:
    _seed_encrypted_sink(db_session)

    resp = await client.get(_SINKS, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert _SECRET_PART not in resp.text
    config = resp.json()[0]["provider_config"]
    assert config["webhook_url"] == "https://hooks.slack.com/services/•••"
    assert config["webhook_url_set"] is True


@pytest.mark.asyncio
async def test_creating_a_sink_does_not_echo_the_webhook_url_back(client, auth_headers) -> None:
    created = await _create_slack_sink(client, auth_headers)

    assert _SECRET_PART not in str(created)


@pytest.mark.asyncio
async def test_the_webhook_url_is_not_stored_in_plaintext(client, auth_headers, db_session) -> None:
    created = await _create_slack_sink(client, auth_headers)

    row = db_session.get(NotificationSink, created["id"])
    assert _SECRET_PART not in str(row.provider_config)
    assert row.provider_config["webhook_url_enc"]


@pytest.mark.asyncio
async def test_patching_a_sink_with_the_masked_url_keeps_the_secret(
    client, auth_headers, db_session
) -> None:
    """The clobber trap: the UI round-trips whatever the read path handed it."""
    from app.services.notification_secrets import decrypt_config

    created = await _create_slack_sink(client, auth_headers)
    masked = created["provider_config"]["webhook_url"]

    resp = await client.patch(
        f"{_SINKS}/{created['id']}",
        json={"name": "Renamed", "provider_config": {"webhook_url": masked}},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    row = db_session.get(NotificationSink, created["id"])
    assert decrypt_config(row.provider_config)["webhook_url"] == _SLACK_URL


@pytest.mark.asyncio
async def test_patching_a_sink_can_still_replace_the_webhook_url(
    client, auth_headers, db_session
) -> None:
    from app.services.notification_secrets import decrypt_config

    created = await _create_slack_sink(client, auth_headers)
    replacement = "https://hooks.slack.com/services/T1/B1/replacedSECRET"

    resp = await client.patch(
        f"{_SINKS}/{created['id']}",
        json={"provider_config": {"webhook_url": replacement}},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    row = db_session.get(NotificationSink, created["id"])
    assert decrypt_config(row.provider_config)["webhook_url"] == replacement


@pytest.mark.asyncio
async def test_a_legacy_plaintext_sink_is_masked_on_read(client, auth_headers, db_session) -> None:
    """Existing installs hold plaintext rows; the leak closes without a migration."""
    sink = NotificationSink(
        name="Legacy",
        provider_type="slack",
        provider_config={"webhook_url": _SLACK_URL},
        enabled=True,
    )
    db_session.add(sink)
    db_session.commit()

    resp = await client.get(_SINKS, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert _SECRET_PART not in resp.text


@pytest.mark.asyncio
async def test_testing_a_sink_posts_to_the_real_webhook_url(client, auth_headers) -> None:
    """Redaction must not reach the delivery path — Test would silently post nowhere."""
    created = await _create_slack_sink(client, auth_headers)
    response = AsyncMock()
    response.status_code = 200

    with patch(
        "app.api.notifications.safe_async_request", AsyncMock(return_value=response)
    ) as sent:
        resp = await client.post(f"{_SINKS}/{created['id']}/test", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert sent.await_args.args[2] == _SLACK_URL
