"""
Global discovery WebSocket stream.

Endpoint: WS /api/v1/discovery/stream

Auth protocol (token-as-first-message):
  1. Client connects.
  2. Server waits up to 10 seconds for the first text message.
  3. First message must be a valid JWT token string (raw, not JSON-wrapped).
  4. Server validates the token. On failure: sends {"error": "unauthorized"}
     and closes with code 1008.
  5. On success: server sends {"status": "connected"} and begins streaming
     job events.

Message types emitted by server:
  {"type": "job_update",   "job": <ScanJobOut dict>}
  {"type": "job_progress", "job_id": int, "message": str}
  {"type": "result_added", "job_id": int, "result": <ScanResultOut dict>}
  {"type": "ping",         "ts": "<utc iso>"}

Message types accepted from client:
  {"type": "ping"}  → server responds with {"type": "pong", "ts": "<utc iso>"}

The server sends a ping every 30 seconds to keep the connection alive.
Clients should reconnect on unexpected close.

Security notes:
- Connections are capped globally (CB_WS_MAX_CONNECTIONS, default 50) and
  per-IP (CB_WS_MAX_PER_IP, default 5) to prevent DoS.
- Auth timeout sends an explicit close frame (code 1008) — no silent drop.
- An auth_timeout error is sent before closing so the client can distinguish
  it from a network fault and avoid an immediate reconnect loop.
- Plain ws:// connections are warned about in production (use WSS).  # nosemgrep
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.forwarded import client_host, forwarded_client_identity, request_from_trusted_proxy
from app.core.rbac import require_role
from app.core.security import decode_token
from app.core.time import utcnow, utcnow_iso
from app.core.ws_manager import ws_manager
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.stream_faults import close_stream_socket, record_stream_fault
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

# REL-07 fault-metric identity for this stream; also the log prefix.
_COMPONENT = "ws_discovery"
_EVENT_CHANNEL = "cb:discovery:events"
# RFC 6455 1011 "internal error" — the server cannot fulfil the stream contract.
_WS_INTERNAL_ERROR = 1011


def trusted_ws_client_ip(websocket: WebSocket) -> str:
    """The client address, honouring `X-Forwarded-For` only behind a trusted proxy.

    Every WebSocket endpoint in this package keys a security decision on this
    value: it is the per-IP connection cap's bucket key, the log identity for
    every rejected handshake, and — on /ws/monitors and the telemetry stream —
    the address the operator's `ws_allowed_cidrs` network allowlist is matched
    against. Whoever gets to choose it gets to choose whether those controls
    apply to them.

    All five streams used to read the *leftmost* `X-Forwarded-For` entry off any
    peer, which handed that choice to the caller twice over: the shipped nginx
    *appends* (`$proxy_add_x_forwarded_for`), so a client's own header survives
    to the left of its real address, and a client that reaches uvicorn directly
    can invent the header outright. So an off-net caller could name an address
    inside the operator's allowlist and be let straight in, or rotate the header
    for a fresh connection budget and make CB_WS_MAX_PER_IP mean nothing.

    app.core.forwarded owns this trust decision for the whole codebase — the
    rate limiter and the security-headers middleware already ask it — so ask it
    here rather than re-deriving it. It walks the chain right to left and stops
    at the first hop outside `trusted_proxy_cidrs`, which is the nearest address
    an attacker cannot forge, and falls back to the socket peer whenever the
    peer is not one of our own proxies.

    This lives here, and ws_telemetry/ws_monitors/ws_topology/ws_agents import
    it, because B24 was exactly the cost of having had five byte-identical
    copies of the old two-line read: the first fix pass corrected two of them and
    left the /ws/monitors allowlist bypass live in the other three. Do not paste
    a sixth copy into a new stream, and do not "simplify" the body back to
    `headers["x-forwarded-for"].split(",")[0]` — that is the bug, not a
    shortcut. The shipped defaults still recover the real client IP:
    `trusted_proxy_cidrs` defaults to loopback and the mono image proxies over
    127.0.0.1, so nothing legitimate loses its identity here.
    """
    if request_from_trusted_proxy(websocket):
        forwarded = forwarded_client_identity(websocket.headers)
        if forwarded:
            return forwarded
    return client_host(websocket) or "unknown"


def _extract_client_ip(websocket: WebSocket) -> str:
    """This stream's cap-bucket key — see `trusted_ws_client_ip` above."""
    return trusted_ws_client_ip(websocket)


def _warn_if_insecure(websocket: WebSocket) -> None:
    """Log a warning when the connection arrives over plain ws:// in production."""  # nosemgrep
    scheme = websocket.headers.get("x-forwarded-proto", "")
    if scheme and scheme.lower() == "http":
        logger.warning(
            "WS connection over plain HTTP detected from %s — "
            "use HTTPS/WSS in production to protect the auth token.",
            _extract_client_ip(websocket),
        )


async def _ping_loop(ws: WebSocket, main_task: asyncio.Task) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            if ws.application_state == WebSocketState.DISCONNECTED:
                main_task.cancel()
                break
            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        # A failed keep-alive send means the peer is gone; cancel the receive
        # loop so teardown runs now instead of at the next 30s tick.
        record_stream_fault(f"{_COMPONENT}.ping", exc, logger=logger)
        main_task.cancel()


async def _redis_discovery_listener(ws: WebSocket, stop_event: asyncio.Event) -> None:
    """Subscribe to the Redis ``cb:discovery:events`` pub/sub channel and
    forward every message to the WebSocket.  This is the primary cross-worker
    delivery mechanism — the scan may run on a different Uvicorn worker than
    the one hosting this WebSocket connection.

    Degrades to no-op when Redis is unavailable (the local
    ``ws_manager.broadcast`` fallback in ``_emit_ws_event`` covers that case).
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        await stop_event.wait()
        return

    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(_EVENT_CHANNEL)
        while not stop_event.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                if ws.application_state == WebSocketState.DISCONNECTED:
                    break
                try:
                    await ws.send_text(msg["data"])
                except Exception as exc:
                    # Forwarding failed: the socket is the only thing this task
                    # feeds, so there is nothing left to do but stop.
                    record_stream_fault(f"{_COMPONENT}.forward", exc, logger=logger)
                    break
            # No asyncio.sleep() — get_message(timeout=1.0) already yields to the event loop.
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        # Redis pub/sub is the *only* cross-worker delivery path for this
        # stream. Losing it used to be a DEBUG line and a silent return, which
        # left the socket open, pinging, and permanently empty — the client had
        # no way to tell a quiet scan queue from a broken fan-out. Classify it,
        # count it, and close the socket so the client reconnects (REL-07).
        record_stream_fault(
            f"{_COMPONENT}.subscribe", exc, logger=logger, context={"channel": _EVENT_CHANNEL}
        )
        await close_stream_socket(ws, component=_COMPONENT, code=_WS_INTERNAL_ERROR)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception as exc:
            record_stream_fault(f"{_COMPONENT}.teardown", exc, logger=logger)


# NOTE: This router is mounted at prefix /api/v1/discovery in main.py.
# All decorator paths here are relative to that prefix.
@router.websocket("/stream")
async def discovery_stream(websocket: WebSocket) -> None:
    # Always accept first — token auth follows as the first message.
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(dict(websocket.scope)):
        try:
            await websocket.send_text(json.dumps({"error": "wss_required"}))
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    client_ip = _extract_client_ip(websocket)
    _warn_if_insecure(websocket)

    try:
        # ── Auth phase: cookie (httpOnly) only ──────────────────────────────
        raw_token = token_from_websocket_scope(dict(websocket.scope))
        if not raw_token:
            logger.warning("WS auth rejected: no session cookie (ip=%s)", client_ip)
            try:
                await websocket.send_text(json.dumps({"error": "unauthorized"}))
                await websocket.close(code=1008)
            except Exception:
                pass
            return

        authenticated = False
        user_id: int | None = None

        with _db_session.SessionLocal() as db:
            cfg = get_or_create_settings(db)
            if cfg.jwt_secret:
                if is_session_revoked(db, raw_token):
                    authenticated = False
                else:
                    uid = decode_token(raw_token, cfg.jwt_secret)
                    if uid is not None:
                        u = db.get(User, uid)
                        if u and u.is_active:
                            if not (u.locked_until and u.locked_until > utcnow()):
                                if not (
                                    u.role == "demo"
                                    and u.demo_expires
                                    and u.demo_expires <= utcnow()
                                ):
                                    authenticated = True
                                    user_id = uid

        if not authenticated:
            logger.warning("WS auth failed (ip=%s)", client_ip)
            try:
                await websocket.send_text(json.dumps({"error": "unauthorized"}))
                await websocket.close(code=1008)
            except Exception:
                pass
            return

        # ── Connection cap check ────────────────────────────────────────────
        accepted = await ws_manager.connect(websocket, user_id=user_id, client_ip=client_ip)
        if not accepted:
            try:
                await websocket.send_text(json.dumps({"error": "connection_limit_exceeded"}))
                await websocket.close(code=1008)
            except Exception:
                pass
            return

        await websocket.send_text(json.dumps({"status": "connected"}))

        # ── Keep-alive + Redis pub/sub listener + receive loop ────────────
        _current_task = asyncio.current_task()
        assert _current_task is not None
        ping_task = asyncio.create_task(_ping_loop(websocket, _current_task))
        redis_stop = asyncio.Event()
        redis_task = asyncio.create_task(_redis_discovery_listener(websocket, redis_stop))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict) and msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            redis_stop.set()
            ping_task.cancel()
            redis_task.cancel()
            await ws_manager.disconnect(websocket)

    except Exception as e:
        logger.error("WS unhandled error (ip=%s): %s", client_ip, e)
        try:
            await ws_manager.disconnect(websocket)
            await websocket.close(code=1011)
        except Exception:
            pass


@router.get("/ws/status")
async def ws_status(user: Any = require_role("admin")) -> dict[str, Any]:
    """Admin-facing endpoint: live WebSocket connection metrics."""
    return ws_manager.status_snapshot()
