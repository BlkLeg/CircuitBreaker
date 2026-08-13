import json
from contextlib import contextmanager

import pytest


@contextmanager
def _auth_enabled(enabled: bool):
    """Deterministically pin AppSettings.auth_enabled for one test and
    restore whatever it was before.

    Needed because the app_cfg fixture (session-scoped, and — like every
    other seed in this codebase that must be visible to a WS handler's own
    SessionLocal() connection, see [[ws-auth-enabled-router-gate]] — commits
    for real via SessionLocal(), not the SAVEPOINT-rolled-back db_session)
    sets auth_enabled=True exactly once per pytest session and that change
    is never rolled back. Once any earlier test in the same run has pulled
    in app_cfg (directly or via `client`), auth_enabled stays True for every
    test after it — so this test cannot assume the fixture default holds.
    """
    from app.db.models import AppSettings
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        cfg = db.query(AppSettings).first()
        original = cfg.auth_enabled if cfg is not None else False
        if cfg is None:
            cfg = AppSettings(id=1)
            db.add(cfg)
        cfg.auth_enabled = enabled
        db.commit()
    try:
        yield
    finally:
        with SessionLocal() as db:
            cfg = db.query(AppSettings).first()
            if cfg is not None:
                cfg.auth_enabled = original
                db.commit()


def test_stream_rejects_cookieless_connection_before_the_app_is_bootstrapped(ws_client):
    """Pre-OOBE, the presence stream is refused rather than opened as admin.

    This used to connect: while `auth_enabled` was false every route ran as the
    admin sentinel, so a cookie-less handshake got through the router and the
    handler's own first-message-token timeout was what eventually closed it.
    First run now only grants that sentinel on the setup surface
    (`app.core.security._PRE_BOOTSTRAP_SETUP_SURFACE`), and an operator presence
    stream is not part of setting the instance up — no agent can enrol before an
    admin exists — so the handshake is rejected outright.

    Note the handler's `_STREAM_AUTH_TIMEOUT_SECONDS` branch is unreachable
    through the router in both states now: bootstrapped, `require_auth` rejects
    a cookie-less handshake; unbootstrapped, this does. It is dead defence in
    depth rather than a live control.
    """
    with _auth_enabled(False):
        with pytest.raises(Exception) as exc_info:  # noqa: B017 - Starlette version varies.
            with ws_client.websocket_connect("/api/v1/agents/stream"):
                pass  # pragma: no cover - connecting at all is the failure.
    denial = str(exc_info.value)
    assert (
        "403" in denial
        or "401" in denial
        or exc_info.type.__name__ in {"WebSocketDisconnect", "WebSocketDenialResponse"}
    )


def _login_viewer(ws_client, app_cfg):
    """Seeds a viewer user via a real committed connection (SessionLocal(),
    matching what agent_presence_stream itself uses) — db_session's
    SAVEPOINT-based isolation would never become visible to the handler's own
    SessionLocal() connection. Same pattern as
    test_ws_agents_link.py::_active_agent_with_key.

    Logs in through ws_client itself (not the separate async `client`
    fixture) so the cb_session cookie lands in ws_client's own cookie jar —
    Starlette's TestClient persists cookies across requests on one instance,
    so the subsequent websocket_connect() automatically attaches it, exactly
    like a real browser's WebSocket constructor would.

    NOTE: once AppSettings.auth_enabled is True (app_cfg sets this),
    core/security.py's resolve_optional_user_id_sync returns None for any
    request with no valid cookie/header — so the router-level
    dependencies=[Depends(require_auth)] on authenticated_router rejects the
    WS handshake with a 401 *before* agent_presence_stream's own body runs
    at all. That means the handler's token-as-first-message fallback (for a
    hypothetical bearer-token, no-cookie client) is unreachable in that
    configuration — a pre-existing characteristic shared by every WS route
    using this same router pattern (ws_discovery.py, ws_monitors.py, ...),
    not something specific to this endpoint. The cookie-login flow below is
    the one path that's actually exercised in production (browsers attach
    cookies to the WS handshake automatically) and is what Task 18/19's
    browser-based useAgentLive.js will rely on.
    """
    import secrets

    from app.core.security import hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.db.session import SessionLocal

    password = "TestPassword123!"
    email = f"stream-test-{secrets.token_hex(4)}@example.com"
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="viewer",
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="Stream Test Viewer",
            provider="local",
            created_at=utcnow_iso(),
        )
        db.add(user)
        db.commit()

    resp = ws_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def test_stream_authenticates_via_session_cookie_and_forwards_broadcast(
    ws_client, app_cfg, monkeypatch
):
    # Redis is unavailable in the unit-test environment, so /stream falls back
    # to receiving pushes directly from ws_manager.broadcast — proven here;
    # the Redis pub/sub cross-worker path mirrors ws_discovery.py's already
    # battle-tested _redis_discovery_listener and isn't re-proven per route.
    from unittest.mock import AsyncMock

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    _login_viewer(ws_client, app_cfg)

    with ws_client.websocket_connect("/api/v1/agents/stream") as ws:
        ack = json.loads(ws.receive_text())
        assert ack["status"] == "connected"

        # Bridge from this sync test body into the ASGI app's own event loop:
        # ws_client.portal is the anyio.abc.BlockingPortal TestClient.__enter__
        # sets up (starlette/testclient.py) to run the app in a background
        # thread — the same loop ws_manager's in-memory connection set lives
        # on, unlike a bare anyio.from_thread.run() call from this thread
        # (which has no worker-thread token and raises NoEventLoopError).
        from app.core.ws_manager import ws_manager

        ws_client.portal.call(
            ws_manager.broadcast, {"agent_id": 9, "event_type": "connected", "detail": None}
        )
        msg = json.loads(ws.receive_text())
        assert msg["agent_id"] == 9
        assert msg["event_type"] == "connected"
