"""Email sink HTTP boundary (INC-02).

The *Test* button and real dispatch used to take different paths — the button
sent through the global SMTP settings while ``notify_email`` read SMTP fields
out of ``provider_config`` that the form never collects. A green test therefore
proved nothing. These tests pin the button to the delivery path and reject a
sink that could never deliver.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import AppSettings

_SINKS = "/api/v1/notifications/sinks"
_TO = "oncall@example.com"


def _configure_smtp(db_session, *, host: str = "smtp.example.com") -> None:
    cfg = db_session.query(AppSettings).first()
    if cfg is None:
        cfg = AppSettings(id=1)
        db_session.add(cfg)
    cfg.smtp_host = host
    cfg.smtp_port = 587
    cfg.smtp_from_email = "circuitbreaker@example.com"
    db_session.commit()


async def _create_email_sink(client, auth_headers, config: dict) -> dict:
    return await client.post(
        _SINKS,
        json={"name": "On-call Email", "provider_type": "email", "provider_config": config},
        headers=auth_headers,
    )


@pytest.mark.asyncio
async def test_an_email_sink_without_a_recipient_is_rejected(client, auth_headers) -> None:
    """A sink with no 'to' can never deliver; refuse it at creation, not at 3am."""
    resp = await _create_email_sink(client, auth_headers, {})

    assert resp.status_code == 422, resp.text
    assert "recipient" in resp.text.lower()


@pytest.mark.asyncio
async def test_an_email_sink_with_a_recipient_is_accepted(client, auth_headers) -> None:
    resp = await _create_email_sink(client, auth_headers, {"to": _TO})

    assert resp.status_code == 200, resp.text
    assert resp.json()["provider_config"]["to"] == _TO


@pytest.mark.asyncio
async def test_patching_an_email_sink_cannot_clear_its_recipient(client, auth_headers) -> None:
    created = (await _create_email_sink(client, auth_headers, {"to": _TO})).json()

    resp = await client.patch(
        f"{_SINKS}/{created['id']}",
        json={"provider_config": {"to": ""}},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_testing_an_email_sink_uses_the_delivery_path(
    client, auth_headers, db_session
) -> None:
    """The whole point of INC-02: Test and dispatch must be the same code."""
    _configure_smtp(db_session)
    created = (await _create_email_sink(client, auth_headers, {"to": _TO})).json()

    with patch("app.services.smtp_service.SmtpService.send_alert", AsyncMock()) as send_alert:
        resp = await client.post(f"{_SINKS}/{created['id']}/test", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    send_alert.assert_awaited_once()
    assert send_alert.await_args.args[0] == _TO


@pytest.mark.asyncio
async def test_testing_an_email_sink_reports_unconfigured_smtp(
    client, auth_headers, db_session
) -> None:
    """The failure operators actually hit — it must name the cause, not a socket error."""
    _configure_smtp(db_session, host="")
    created = (await _create_email_sink(client, auth_headers, {"to": _TO})).json()

    resp = await client.post(f"{_SINKS}/{created['id']}/test", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "SMTP is not configured" in body["error"]
