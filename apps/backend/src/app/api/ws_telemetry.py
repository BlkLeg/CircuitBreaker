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
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.network_acl import is_ip_in_cidrs as _is_ip_in_cidrs
from app.core.redis import get_redis
from app.core.security import _get_api_token, decode_token
from app.core.time import utcnow, utcnow_iso
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_CONNECTIONS: int = int(os.getenv("CB_WS_TELEM_MAX_CONNECTIONS", "100"))
_MAX_PER_IP: int = int(os.getenv("CB_WS_TELEM_MAX_PER_IP", "10"))
_MAX_SUBSCRIPTIONS: int = 200

_connections: set[WebSocket] = set()
_ip_counts: dict[str, int] = {}
_lock = asyncio.Lock()


def _extract_client_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


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
    async with _lock:
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
                try:
                    data = json.loads(msg["data"])
                    await ws.send_text(json.dumps({"type": "telemetry", **data}))
                except Exception as exc:
                    logger.debug("Telemetry WS forward failed: %s", exc)
                    break
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("Redis listener error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


async def _ping_loop(ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            if ws.application_state == WebSocketState.DISCONNECTED:
                break
            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


@router.websocket("/stream")
async def telemetry_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(websocket.scope):
        try:
            await websocket.send_text(json.dumps({"error": "wss_required"}))
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    client_ip = _extract_client_ip(websocket)

    try:
        # ── Auth phase ──────────────────────────────────────────────────
        raw_token = token_from_websocket_scope(websocket.scope)
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
        api_token = _get_api_token()

        if api_token and raw_token == api_token:
            authenticated = True
        else:
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
        ping_task = asyncio.create_task(_ping_loop(websocket))

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
                        new_channels = {
                            f"telemetry:{eid}"
                            for eid in entity_ids[:_MAX_SUBSCRIPTIONS]
                            if isinstance(eid, int)
                        }
                        subscribed_channels.update(new_channels)
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
                        for eid in entity_ids:
                            subscribed_channels.discard(f"telemetry:{eid}")
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
