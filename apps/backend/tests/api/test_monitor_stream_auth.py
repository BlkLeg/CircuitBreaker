import json
import secrets
from datetime import UTC, datetime, timedelta

import pytest


def _login_user(
    ws_client, *, role: str = "viewer", tenant_id: int | None = None
) -> tuple[str, int]:
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
            role=role,
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="Monitor Stream Viewer",
            provider="local",
            created_at=utcnow_iso(),
            tenant_id=tenant_id,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    resp = ws_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"], user_id


def _login_viewer(ws_client, app_cfg) -> tuple[str, int]:
    return _login_user(ws_client)


def _create_committed_monitor(*, tenant_id: int | None = None) -> int:
    from app.db.models import Hardware, MonitorItem
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        hardware = Hardware(
            name=f"monitor-stream-hw-{secrets.token_hex(4)}",
            ip_address=f"192.0.2.{secrets.randbelow(100) + 10}",
            tenant_id=tenant_id,
        )
        db.add(hardware)
        db.flush()
        monitor = MonitorItem(
            name=f"monitor-stream-{secrets.token_hex(4)}",
            check_type="icmp",
            host=hardware.ip_address,
            params={},
            interval_secs=60,
            max_retries=2,
            enabled=True,
            target_type="hardware",
            target_id=hardware.id,
            last_status="pending",
        )
        db.add(monitor)
        db.commit()
        return monitor.id


def _create_committed_tenant(name: str) -> int:
    from app.db.models import Tenant
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        tenant = Tenant(name=f"{name}-{secrets.token_hex(4)}")
        db.add(tenant)
        db.commit()
        return tenant.id


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


def test_monitor_stream_rejects_revoked_session_on_reconnect(ws_client, app_cfg, monkeypatch):
    from unittest.mock import AsyncMock

    from app.db.session import SessionLocal

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))
    token, user_id = _login_viewer(ws_client, app_cfg)

    with ws_client.websocket_connect("/api/v1/monitors/stream") as ws:
        assert json.loads(ws.receive_text()) == {"status": "connected"}

    with SessionLocal() as db:
        from datetime import timedelta

        from app.core.time import utcnow
        from app.db.models import UserSession
        from app.services.user_service import _hash_token

        db.add(
            UserSession(
                user_id=user_id,
                jwt_token_hash=_hash_token(token),
                expires_at=utcnow() + timedelta(hours=1),
                revoked=True,
            )
        )
        db.commit()

    with ws_client.websocket_connect("/api/v1/monitors/stream") as ws:
        assert json.loads(ws.receive_text()) == {"error": "unauthorized"}
        with pytest.raises(Exception) as exc_info:  # noqa: B017 - Starlette version varies here.
            ws.receive_text()

    assert getattr(exc_info.value, "code", None) in {1008, 4401}


def test_monitor_stream_filters_wrong_tenant_subscriptions(ws_client, app_cfg, monkeypatch):
    from unittest.mock import AsyncMock

    captured: list[set[str]] = []

    async def capture_listener(_websocket, channels, stop_event):
        captured.append(set(channels))
        await stop_event.wait()

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.ws_monitors._redis_listener", capture_listener)

    tenant_a = _create_committed_tenant("monitor-stream-a")
    tenant_b = _create_committed_tenant("monitor-stream-b")
    hidden_mid = _create_committed_monitor(tenant_id=tenant_a)
    visible_mid = _create_committed_monitor(tenant_id=tenant_b)
    _login_user(ws_client, tenant_id=tenant_b)

    with ws_client.websocket_connect("/api/v1/monitors/stream") as ws:
        assert json.loads(ws.receive_text()) == {"status": "connected"}
        ws.send_text(json.dumps({"subscribe": [hidden_mid, visible_mid, 999999]}))
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text())["type"] == "pong"

    assert captured
    assert f"monitor:{visible_mid}" in captured[-1]
    assert f"monitor:{hidden_mid}" not in captured[-1]
    assert "monitor:999999" not in captured[-1]


@pytest.mark.parametrize(
    ("token_scopes", "accepted"),
    [(["read:*"], True), (["write:*"], False), ([], False)],
)
def test_monitor_stream_service_jwt_requires_read_scope(
    ws_client, app_cfg, db_session, token_scopes, accepted
):
    from app.core.security import create_token
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db_session)
    token = create_token(
        0,
        cfg.jwt_secret,
        1,
        scopes=token_scopes,
        extra_claims={"label": "SEC-08 monitor stream service token"},
    )

    with ws_client.websocket_connect(
        "/api/v1/monitors/stream",
        headers={"Authorization": f"Bearer {token}"},
    ) as ws:
        ws.send_text(token)
        first = json.loads(ws.receive_text())
        if accepted:
            assert first == {"status": "connected"}
        else:
            assert first == {"error": "unauthorized"}
            with pytest.raises(Exception) as exc_info:  # noqa: B017
                ws.receive_text()
            assert getattr(exc_info.value, "code", None) in {1008, 4401}


def test_monitor_stream_rejects_expired_demo_identity(ws_client, app_cfg):
    from app.core.security import create_token, hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings

    password = "TestPassword123!"
    email = f"monitor-stream-expired-demo-{secrets.token_hex(4)}@example.com"
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="demo",
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="Expired Demo",
            provider="local",
            created_at=utcnow_iso(),
            demo_expires=datetime.now(UTC) - timedelta(minutes=1),
        )
        db.add(user)
        db.commit()
        cfg = get_or_create_settings(db)
        token = create_token(user.id, cfg.jwt_secret, 1, role="demo")

    with pytest.raises(Exception) as exc_info:  # noqa: B017 - Starlette version varies here.
        with ws_client.websocket_connect(
            "/api/v1/monitors/stream",
            headers={"Authorization": f"Bearer {token}"},
        ):
            pass

    status_code = getattr(exc_info.value, "status_code", None)
    close_code = getattr(exc_info.value, "code", None)
    assert status_code in {401, 403} or close_code in {1008, 4401}
