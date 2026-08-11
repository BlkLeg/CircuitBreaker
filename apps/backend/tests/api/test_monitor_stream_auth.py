import json
import secrets

import pytest


def _login_viewer(ws_client, app_cfg) -> None:
    from app.core.security import hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.db.session import SessionLocal

    password = "TestPassword123!"
    email = f"monitor-stream-{secrets.token_hex(4)}@example.com"
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="viewer",
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="Monitor Stream Viewer",
            provider="local",
            created_at=utcnow_iso(),
        )
        db.add(user)
        db.commit()

    resp = ws_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def test_monitor_stream_rejects_unauthenticated_handshake(ws_client, app_cfg):
    with pytest.raises(Exception) as exc_info:  # noqa: B017 - Starlette version varies here.
        with ws_client.websocket_connect("/api/v1/monitors/stream"):
            pass

    status_code = getattr(exc_info.value, "status_code", None)
    close_code = getattr(exc_info.value, "code", None)
    assert status_code in {401, 403} or close_code in {1008, 4401}


def test_monitor_stream_accepts_session_cookie(ws_client, app_cfg, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))
    _login_viewer(ws_client, app_cfg)

    with ws_client.websocket_connect("/api/v1/monitors/stream") as ws:
        assert json.loads(ws.receive_text()) == {"status": "connected"}
        ws.send_text(json.dumps({"type": "ping"}))
        pong = json.loads(ws.receive_text())
        assert pong["type"] == "pong"
