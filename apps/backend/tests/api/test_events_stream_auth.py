from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_events_stream_rejects_anonymous_client(client):
    async with client.stream("GET", "/api/v1/events/stream") as resp:
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_stream_accepts_viewer_session(client, viewer_headers, monkeypatch):
    from app.api import events

    async def finite_stream():
        yield ": keepalive\n\n"

    monkeypatch.setattr(events.nats_client, "_connected", False)
    monkeypatch.setattr(events, "_db_poll_generator", lambda: finite_stream())

    async with client.stream("GET", "/api/v1/events/stream", headers=viewer_headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_events_stream_rejects_revoked_session_on_reconnect(
    client, db_session, viewer_login, monkeypatch
):
    from app.api import events
    from app.services.user_service import revoke_token_session

    async def finite_stream():
        yield ": keepalive\n\n"

    monkeypatch.setattr(events.nats_client, "_connected", False)
    monkeypatch.setattr(events, "_db_poll_generator", lambda: finite_stream())

    token, csrf = viewer_login
    headers = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}

    async with client.stream("GET", "/api/v1/events/stream", headers=headers) as first:
        assert first.status_code == 200

    assert revoke_token_session(db_session, token) is True

    async with client.stream("GET", "/api/v1/events/stream", headers=headers) as reconnect:
        assert reconnect.status_code == 401
