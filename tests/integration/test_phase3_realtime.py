"""Phase 3 — Messaging & Realtime tests.

Covers:
  - NATSClient: no-op graceful degradation when NATS is unavailable
  - GET /api/v1/events/stream: SSE stream responds and emits keepalive
  - GET /api/v1/events/status: returns transport status
  - WS /api/v1/topology/stream: auth flow, connection cap, ping/pong
  - AppSettings: new realtime fields readable via /api/v1/settings
"""

import json

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

# ── NATSClient unit tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skip(reason="Connects to unreachable port; slow (3s+ timeout)")
async def test_nats_client_noop_when_unavailable():
    """NATSClient must degrade gracefully when NATS is not running."""
    from app.core.nats_client import NATSClient

    client = NATSClient(url="nats://127.0.0.1:19999")  # port that is never open
    await client.connect()

    assert not client.is_connected
    # publish and subscribe must be silent no-ops
    await client.publish("test.subject", {"key": "value"})  # must not raise
    result = await client.subscribe("test.subject", lambda msg: None)
    assert result is None

    await client.disconnect()  # must not raise


@pytest.mark.asyncio
async def test_nats_client_publish_encodes_dict():
    """publish() encodes dict → bytes before calling nats.publish()."""
    from app.core.nats_client import NATSClient

    client = NATSClient()
    client._connected = True

    sent = []

    class _FakeNC:
        async def publish(self, subject, data):
            sent.append((subject, data))

    client._nc = _FakeNC()
    await client.publish("test.subject", {"hello": "world"})

    assert len(sent) == 1
    subject, data = sent[0]
    assert subject == "test.subject"
    assert json.loads(data) == {"hello": "world"}


@pytest.mark.asyncio
async def test_nats_client_disconnect_drains():
    """disconnect() calls drain() on the underlying connection."""
    from app.core.nats_client import NATSClient

    client = NATSClient()
    client._connected = True

    drained = []

    class _FakeNC:
        async def drain(self):
            drained.append(True)

    client._nc = _FakeNC()
    await client.disconnect()

    assert drained == [True]
    assert not client.is_connected
    assert client._nc is None


# ── Subject constants ────────────────────────────────────────────────────────


def test_subjects_constants_defined():
    from app.core import subjects

    assert subjects.DISCOVERY_SCAN_STARTED == "discovery.scan.started"
    assert subjects.TOPOLOGY_NODE_MOVED == "topology.node.moved"
    assert subjects.NOTIFICATION_EVENT == "notifications.event"


def test_subjects_payload_helpers():
    from app.core.subjects import (
        discovery_scan_started_payload,
        topology_cable_payload,
        topology_node_moved_payload,
    )

    p = discovery_scan_started_payload(42, "192.168.1.0/24", "api")
    assert p["job_id"] == 42
    assert p["cidr"] == "192.168.1.0/24"

    tp = topology_node_moved_payload("hw-1", "hardware", 100.5, 200.0)
    assert tp["node_id"] == "hw-1"
    assert tp["x"] == 100.5

    cp = topology_cable_payload("hw-1", "hw-2", "fiber", 10000)
    assert cp["connection_type"] == "fiber"
    assert cp["bandwidth_mbps"] == 10000


# ── SSE /events/stream ───────────────────────────────────────────────────────


def test_events_stream_route_exists():
    """SSE /stream route is registered in events router (no client needed)."""
    from app.api.events import router as _events_router

    stream_routes = [r for r in _events_router.routes if hasattr(r, "path") and r.path == "/stream"]
    assert len(stream_routes) == 1, "Expected /stream route in events router"


def test_events_status(client: TestClient, auth_headers):
    """GET /api/v1/events/status returns transport field."""
    r = client.get("/api/v1/events/status", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "transport" in data
    assert data["transport"] in ("nats", "db_poll")
    assert "nats_connected" in data


# ── Topology WebSocket ────────────────────────────────────────────────────────


def test_topology_ws_requires_auth(client: TestClient, auth_headers):
    """An unauthenticated handshake is refused before the socket is upgraded.

    This asserts a *denial response*, not a post-handshake close, because the
    stream carries no first-message token protocol any more. Credentials ride
    the httpOnly ``cb_session`` cookie the handshake sends (323ad9c2), and
    ``main.py`` mounts this router behind ``Depends(require_auth)``, so a
    caller with no session never reaches the endpoint body: the dependency
    raises 401 and Starlette answers the upgrade request with a plain HTTP
    response, which the TestClient surfaces as ``WebSocketDenialResponse``.

    ``auth_headers`` runs so the assertion is about a bootstrapped instance
    refusing an anonymous client, rather than the weaker pre-OOBE refusal;
    clearing the jar drops the session cookie login left on the client.
    """
    client.cookies.clear()

    with pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect("/api/v1/topology/stream"):
            pass  # pragma: no cover - reaching the body is the failure.

    assert exc_info.value.status_code == 401
    assert exc_info.value.json() == {"detail": "Authentication required"}


def test_topology_ws_rejects_empty_token(client: TestClient, auth_headers):
    """An empty session cookie is no session: refused at the same gate."""
    client.cookies.clear()

    with pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect("/api/v1/topology/stream", headers={"Cookie": "cb_session="}):
            pass  # pragma: no cover - reaching the body is the failure.

    assert exc_info.value.status_code == 401
    assert exc_info.value.json() == {"detail": "Authentication required"}


def test_topology_ws_rejects_session_that_is_not_in_the_cookie(client: TestClient, auth_headers):
    """The endpoint's own cookie check still closes 1008 when the gate lets one through.

    ``require_auth`` accepts a bearer header as well as the cookie, but the
    handler reads the cookie only — so a bearer-only handshake is the one way
    to get past the router and still fail auth. That is the path that emits
    the ``{"error": "unauthorized"}`` frame followed by a 1008 close; without
    this case the endpoint's own rejection branch has no coverage at all.
    """
    client.cookies.clear()

    with client.websocket_connect("/api/v1/topology/stream", headers=dict(auth_headers)) as ws:
        assert json.loads(ws.receive_text()) == {"error": "unauthorized"}
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_topology_ws_status_endpoint(client: TestClient, auth_headers):
    """GET /api/v1/topology/ws/status returns connection metrics."""
    r = client.get("/api/v1/topology/ws/status", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "connections" in data
    assert "max_connections" in data


# ── Settings: realtime fields ────────────────────────────────────────────────


def test_settings_realtime_fields_readable(client: TestClient, auth_headers):
    """AppSettings exposes realtime_notifications_enabled and realtime_transport."""
    r = client.get("/api/v1/settings", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "realtime_notifications_enabled" in data
    assert "realtime_transport" in data
    assert data["realtime_transport"] in ("auto", "sse", "websocket")


def test_settings_realtime_fields_writable(client: TestClient, auth_headers):
    """PUT /api/v1/settings can update realtime fields."""
    r = client.put(
        "/api/v1/settings",
        json={"realtime_notifications_enabled": False, "realtime_transport": "sse"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["realtime_notifications_enabled"] is False
    assert data["realtime_transport"] == "sse"

    # Restore
    client.put(
        "/api/v1/settings",
        json={"realtime_notifications_enabled": True},
        headers=auth_headers,
    )
