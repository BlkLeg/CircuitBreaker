"""
Telemetry WebSocket stream — pushes live telemetry via Redis pub/sub.

Endpoint: WS /api/v1/telemetry/stream

Clients subscribe to entity telemetry channels by sending:
  {"subscribe": [5, 12, 34]}     — subscribe to telemetry:{5}, telemetry:{12}, ...
  {"unsubscribe": [12]}          — remove specific subscriptions
  {"type": "ping"}               — keep-alive; server responds with pong

Server pushes:
  {"type": "telemetry", "entity_id": 5, "data": {...}, "status": "healthy"}

Auth protocol (identical to ws_topology.py):
  1. Client connects.
  2. First message must be a valid JWT token.
  3. On success: {"status": "connected"}.

Falls back to no-op if Redis is unavailable (WebSocket stays open but receives
no push events; client should poll REST as fallback).

A connection may hold at most `_MAX_SUBSCRIPTIONS` distinct channels in total,
not per frame; exceeding it is a policy violation ({"error":
"subscription_limit_exceeded"}, close 1008) like the other rejections here.
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.api.ws_discovery import trusted_ws_client_ip
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.network_acl import is_ip_in_cidrs as _is_ip_in_cidrs
from app.core.redis import get_redis
from app.core.security import decode_token
from app.core.time import utcnow, utcnow_iso
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.stream_faults import close_stream_socket, record_stream_fault
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

# REL-07 fault-metric identity for this stream.
_COMPONENT = "ws_telemetry"
# RFC 6455 1011 "internal error" — the server cannot fulfil the stream contract.
_WS_INTERNAL_ERROR = 1011

_MAX_CONNECTIONS: int = int(os.getenv("CB_WS_TELEM_MAX_CONNECTIONS", "100"))
_MAX_PER_IP: int = int(os.getenv("CB_WS_TELEM_MAX_PER_IP", "10"))
_MAX_SUBSCRIPTIONS: int = 200

_connections: set[WebSocket] = set()
_ip_counts: dict[str, int] = {}
_lock = asyncio.Lock()


def _extract_client_ip(websocket: WebSocket) -> str:
    """This stream leans on the client address twice, and both are security decisions.

    It is the `_MAX_PER_IP` cap bucket, and it is what the operator's
    `ws_allowed_cidrs` allowlist is matched against below — so a caller who can
    pick this value picks whether the network ACL applies to it. The trust rule
    is shared with every other WS stream; see `trusted_ws_client_ip` in
    ws_discovery.py for what it does and what must not be undone.
    """
    return trusted_ws_client_ip(websocket)


async def _check_limits(client_ip: str) -> bool:
    async with _lock:
        if len(_connections) >= _MAX_CONNECTIONS:
            return False
        if _ip_counts.get(client_ip, 0) >= _MAX_PER_IP:
            return False
        return True


async def _register(ws: WebSocket, client_ip: str) -> None:
    async with _lock:
        _connections.add(ws)
        _ip_counts[client_ip] = _ip_counts.get(client_ip, 0) + 1


async def _unregister(ws: WebSocket, client_ip: str) -> None:
    """Drop one registered connection. Idempotent — calling it twice is a no-op.

    The handler can reach this twice for one socket: the receive loop's
    `finally` always unregisters, and the outer `except Exception` unregisters
    again on its way to close(1011). It can also reach it for a socket that was
    never registered, when the failure happened during the auth or ACL phase.
    Both used to corrupt the tally, because the old body decremented
    unconditionally and treated a count of 0 as `<= 1`: the second call *popped
    the IP key outright*, wiping the count for every other live connection from
    that address and letting it open `_MAX_PER_IP` more. Gating on membership in
    `_connections` — the same set that `_register` adds to under the same lock —
    makes the pairing exact. Do not drop the guard to save a lookup.
    """
    async with _lock:
        if ws not in _connections:
            return
        _connections.discard(ws)
        current = _ip_counts.get(client_ip, 0)
        if current <= 1:
            _ip_counts.pop(client_ip, None)
        else:
            _ip_counts[client_ip] = current - 1


async def _redis_listener(ws: WebSocket, channels: set[str], stop_event: asyncio.Event) -> None:
    """Subscribe to Redis pub/sub channels and forward messages to the WebSocket."""
    r = await get_redis()
    if r is None:
        await stop_event.wait()
        return

    pubsub = r.pubsub()
    try:
        if channels:
            await pubsub.subscribe(*channels)

        while not stop_event.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                # Decoding the publisher's payload and writing to this client's
                # socket are separate failures with opposite correct responses.
                # They used to share one handler that broke the loop for both,
                # so a single malformed message from any publisher silently
                # ended telemetry for a connected client until it reconnected.
                try:
                    payload = json.dumps({"type": "telemetry", **json.loads(msg["data"])})
                except Exception as exc:
                    record_stream_fault(
                        f"{_COMPONENT}.decode",
                        exc,
                        logger=logger,
                        context={"channels": len(channels)},
                    )
                    continue
                try:
                    await ws.send_text(payload)
                except Exception as exc:
                    record_stream_fault(f"{_COMPONENT}.forward", exc, logger=logger)
                    break
            # No asyncio.sleep() here — get_message(timeout=1.0) already yields
            # to the event loop for up to 1s. An extra 50ms sleep was causing
            # ~20 wakeups/second per connection, starving the event loop under load.
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        # The subscription itself is gone; this socket can never carry another
        # telemetry frame, so close it explicitly rather than leave it open and
        # silent behind the keep-alive ping (REL-07).
        record_stream_fault(
            f"{_COMPONENT}.subscribe", exc, logger=logger, context={"channels": len(channels)}
        )
        await close_stream_socket(ws, component=_COMPONENT, code=_WS_INTERNAL_ERROR)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception as exc:
            record_stream_fault(f"{_COMPONENT}.teardown", exc, logger=logger)


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
        # Send failed — client disconnected. Cancel the receive loop immediately
        # so the handler's finally block runs without waiting 30s for the next ping.
        record_stream_fault(f"{_COMPONENT}.ping", exc, logger=logger)
        main_task.cancel()


@router.websocket("/stream")
async def telemetry_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(dict(websocket.scope)):
        try:
            await websocket.send_text(json.dumps({"error": "wss_required"}))
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    client_ip = _extract_client_ip(websocket)

    try:
        # ── Auth phase ──────────────────────────────────────────────────
        raw_token = token_from_websocket_scope(dict(websocket.scope))
        if not raw_token:
            try:
                raw_token = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            except TimeoutError:
                await websocket.send_text(json.dumps({"error": "auth_timeout"}))
                await websocket.close(code=1008)
                return
            except WebSocketDisconnect:
                return

        authenticated = False

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

        if not authenticated:
            logger.warning("Telemetry WS auth failed (ip=%s)", client_ip)
            await websocket.send_text(json.dumps({"error": "unauthorized"}))
            await websocket.close(code=1008)
            return

        # ── CIDR whitelist ──────────────────────────────────────────────
        with _db_session.SessionLocal() as _ws_db:
            _ws_cfg = get_or_create_settings(_ws_db)
            _ws_cidrs = getattr(_ws_cfg, "ws_allowed_cidrs", "[]") or "[]"
        if not _is_ip_in_cidrs(client_ip, _ws_cidrs):
            logger.warning("Telemetry WS rejected by CIDR whitelist (ip=%s)", client_ip)
            await websocket.send_text(json.dumps({"error": "ip_not_allowed"}))
            await websocket.close(code=1008)
            return

        # ── Connection cap ──────────────────────────────────────────────
        if not await _check_limits(client_ip):
            await websocket.send_text(json.dumps({"error": "connection_limit_exceeded"}))
            await websocket.close(code=1008)
            return

        await _register(websocket, client_ip)
        await websocket.send_text(json.dumps({"status": "connected"}))

        # ── Redis pub/sub + receive loop ────────────────────────────────
        subscribed_channels: set[str] = set()
        stop_event = asyncio.Event()
        listener_task: asyncio.Task | None = None
        _current_task = asyncio.current_task()
        assert _current_task is not None
        ping_task = asyncio.create_task(_ping_loop(websocket, _current_task))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
                    continue

                if isinstance(msg, dict) and "subscribe" in msg:
                    entity_ids = msg["subscribe"]
                    if isinstance(entity_ids, list):
                        new_channels = set()
                        for entity in entity_ids[:_MAX_SUBSCRIPTIONS]:
                            if isinstance(entity, int):
                                new_channels.add(f"telemetry:{entity}")
                            elif isinstance(entity, dict):
                                entity_type = entity.get("entity_type")
                                entity_id = entity.get("entity_id")
                                if entity_type == "agent" and isinstance(entity_id, int):
                                    new_channels.add(f"telemetry:agent:{entity_id}")
                                elif entity_type == "hardware" and isinstance(entity_id, int):
                                    new_channels.add(f"telemetry:{entity_id}")
                        # What this frame actually asks for that we are not
                        # already subscribed to. Computed before the merge
                        # because the merge destroys the answer.
                        added = new_channels - subscribed_channels
                        subscribed_channels.update(new_channels)
                        # `_MAX_SUBSCRIPTIONS` used to bound only the slice
                        # taken from *this* frame, while every frame was merged
                        # into one accumulating set — so a client could send
                        # frame after frame of fresh entity ids and hold an
                        # unbounded channel set on a single authenticated
                        # socket, making the server pay an O(n) Redis
                        # unsubscribe/resubscribe on each one. Cap the total,
                        # which is the quantity that actually costs memory and
                        # pub/sub work, and do it *before* the resubscribe below
                        # so the offending frame never pays for it. `break`
                        # leaves the receive loop for the existing `finally`,
                        # which stops the listener, cancels the ping task and
                        # unregisters the connection — no teardown belongs here.
                        if len(subscribed_channels) > _MAX_SUBSCRIPTIONS:
                            await websocket.send_text(
                                json.dumps({"error": "subscription_limit_exceeded"})
                            )
                            await websocket.close(code=1008)
                            break
                        # B25's other half: capping the set stops it growing,
                        # but a client that resends the *same* ids still made
                        # the server cancel the listener, UNSUBSCRIBE every
                        # channel, close the pubsub and issue a fresh N-channel
                        # SUBSCRIBE — an O(n) Redis round trip per frame, at
                        # zero cost to the sender, for a subscription set that
                        # did not change. Only rebuild when this frame adds
                        # something (or when there is no listener yet, which is
                        # also how the very first, possibly empty, subscribe
                        # frame starts one). Removals still rebuild: that is the
                        # unsubscribe branch below, and it has to.
                        if added or listener_task is None:
                            if listener_task:
                                stop_event.set()
                                listener_task.cancel()
                                try:
                                    await listener_task
                                except (asyncio.CancelledError, Exception):
                                    pass
                            stop_event = asyncio.Event()
                            listener_task = asyncio.create_task(
                                _redis_listener(websocket, subscribed_channels, stop_event)
                            )

                if isinstance(msg, dict) and "unsubscribe" in msg:
                    entity_ids = msg["unsubscribe"]
                    if isinstance(entity_ids, list):
                        for entity in entity_ids:
                            if isinstance(entity, int):
                                subscribed_channels.discard(f"telemetry:{entity}")
                            elif isinstance(entity, dict):
                                entity_type, entity_id = (
                                    entity.get("entity_type"),
                                    entity.get("entity_id"),
                                )
                                if entity_type == "agent" and isinstance(entity_id, int):
                                    subscribed_channels.discard(f"telemetry:agent:{entity_id}")
                                elif entity_type == "hardware" and isinstance(entity_id, int):
                                    subscribed_channels.discard(f"telemetry:{entity_id}")
                        if listener_task:
                            stop_event.set()
                            listener_task.cancel()
                            try:
                                await listener_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        if subscribed_channels:
                            stop_event = asyncio.Event()
                            listener_task = asyncio.create_task(
                                _redis_listener(websocket, subscribed_channels, stop_event)
                            )
                        else:
                            listener_task = None

        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()
            ping_task.cancel()
            if listener_task:
                listener_task.cancel()
            await _unregister(websocket, client_ip)

    except Exception as exc:
        logger.error("Telemetry WS unhandled error (ip=%s): %s", client_ip, exc)
        try:
            await _unregister(websocket, client_ip)
            await websocket.close(code=1011)
        except Exception:
            pass
