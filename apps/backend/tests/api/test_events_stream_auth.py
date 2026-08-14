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
    monkeypatch.setattr(events, "_db_poll_generator", lambda _token: finite_stream())

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
    monkeypatch.setattr(events, "_db_poll_generator", lambda _token: finite_stream())

    token, csrf = viewer_login
    headers = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}

    async with client.stream("GET", "/api/v1/events/stream", headers=headers) as first:
        assert first.status_code == 200

    assert revoke_token_session(db_session, token) is True

    async with client.stream("GET", "/api/v1/events/stream", headers=headers) as reconnect:
        assert reconnect.status_code == 401


# ── Mid-stream revocation ────────────────────────────────────────────────────
#
# The checks above only prove a *new* connection is refused. An SSE stream a
# dashboard holds open is the case that matters: before this, revoking a session
# left it receiving alert events until the client chose to disconnect.
#
# `_session_still_valid` deliberately opens its own SessionLocal — a live stream
# has no request-scoped session — so it cannot see the test's SAVEPOINT. These
# tests therefore commit the user through their own session, the same way the
# monitor-stream suite does; conftest's reaper cleans the rows up.


@pytest.fixture
def committed_viewer(ws_client, app_cfg):
    """A viewer whose row *and* session row are visible to a fresh DB connection.

    The session is recorded directly rather than by calling /auth/login: the
    client's `get_db` is the test's SAVEPOINT session, so a login-created
    UserSession would be invisible to the stream's own connection and revoking
    it would be a no-op.
    """
    import secrets

    from app.core.security import hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import record_session

    password = "TestPassword123!"
    email = f"sse-revocation-{secrets.token_hex(4)}@example.com"
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="viewer",
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="SSE Revocation Viewer",
            provider="local",
            created_at=utcnow_iso(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        cfg = get_or_create_settings(db)
        token = _mint_session_jwt(user, cfg.jwt_secret)
        record_session(db, user, None, token, cfg)
        db.commit()
    return token


def _mint_session_jwt(user, jwt_secret):
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    from app.core.security import SESSION_AUDIENCE

    return pyjwt.encode(
        {
            "user_id": user.id,
            "sub": str(user.id),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "aud": SESSION_AUDIENCE,
            "role": user.role,
            "scopes": [],
        },
        jwt_secret,
        algorithm="HS256",
    )


def _revoke(token):
    from app.db.session import SessionLocal
    from app.services.user_service import revoke_token_session

    with SessionLocal() as db:
        revoked = revoke_token_session(db, token)
        db.commit()
    return revoked


def test_session_still_valid_flips_false_once_revoked(committed_viewer):
    from app.api.events import _session_still_valid

    assert _session_still_valid(committed_viewer) is True
    assert _revoke(committed_viewer) is True
    assert _session_still_valid(committed_viewer) is False


def test_session_still_valid_rejects_unknown_and_missing_tokens(committed_viewer):
    from app.api.events import _session_still_valid

    assert _session_still_valid(None) is False
    assert _session_still_valid("not-a-jwt") is False


@pytest.mark.asyncio
async def test_live_stream_emits_terminal_frame_when_session_is_revoked(committed_viewer):
    """The generator must stop on its own, without the client disconnecting."""
    from app.api import events

    # `next_check` in the past, so each call re-checks rather than waiting 15 s.
    assert await events._revoked_frame(committed_viewer, {"next_check": 0.0}) is None

    assert _revoke(committed_viewer) is True

    frame = await events._revoked_frame(committed_viewer, {"next_check": 0.0})
    assert frame == "event: session_revoked\ndata: {}\n\n"


@pytest.mark.asyncio
async def test_revocation_check_is_rate_limited_between_intervals(monkeypatch):
    """A 2 s poll loop must not become a 2 s auth query."""
    import time

    from app.api import events

    calls = []

    def _spy(raw_token):
        calls.append(raw_token)
        return False  # would end the stream if it were consulted

    monkeypatch.setattr(events, "_session_still_valid", _spy)
    state = {"next_check": time.monotonic() + events._REVALIDATE_INTERVAL_S}
    assert await events._revoked_frame("any-token", state) is None
    assert calls == []


@pytest.mark.asyncio
async def test_revocation_check_fails_closed_when_validation_errors(monkeypatch):
    from app.api import events

    def _boom(raw_token):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(events, "_session_still_valid", _boom)
    frame = await events._revoked_frame("any-token", {"next_check": 0.0})
    assert frame == "event: session_revoked\ndata: {}\n\n"
