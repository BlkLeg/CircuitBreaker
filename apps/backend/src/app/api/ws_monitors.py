"""
Monitor status WebSocket stream — pushes live check results via Redis pub/sub.

Endpoint: WS /api/v1/monitors/stream

Clients subscribe to monitor status channels by sending:
  {"subscribe": [5, 12, 34]}     — subscribe to monitor:{5}, monitor:{12}, ...
  {"unsubscribe": [12]}          — remove specific subscriptions
  {"type": "ping"}               — keep-alive; server responds with pong

Server pushes:
  {"type": "monitor_status", "monitor_id": 5, "status": "up|down",
   "msg": "...", "ts": "..."}

Auth protocol (identical to ws_telemetry.py):
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
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.api.ws_discovery import trusted_ws_client_ip
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.network_acl import is_ip_in_cidrs as _is_ip_in_cidrs
from app.core.rbac import effective_scopes, has_scope
from app.core.redis import get_redis
from app.core.security import (
    SESSION_AUDIENCE,
    service_account_token_is_live,
    verify_salted_api_token_hash,
)
from app.core.time import utcnow, utcnow_iso
from app.db.models import APIToken, User
from app.services import monitor_service
from app.services.settings_service import get_or_create_settings
from app.services.stream_faults import close_stream_socket, record_stream_fault
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

# REL-07 fault-metric identity for this stream.
_COMPONENT = "ws_monitors"
# RFC 6455 1011 "internal error" — the server cannot fulfil the stream contract.
_WS_INTERNAL_ERROR = 1011

_MAX_CONNECTIONS: int = int(os.getenv("CB_WS_MON_MAX_CONNECTIONS", "100"))
_MAX_PER_IP: int = int(os.getenv("CB_WS_MON_MAX_PER_IP", "10"))
_MAX_SUBSCRIPTIONS: int = 500
# Doubles as the revocation re-check interval — see _ping_loop. This is the
# upper bound on how long a revoked session keeps receiving monitor data.
_PING_INTERVAL_SECONDS: int = 30

_connections: set[WebSocket] = set()
_ip_counts: dict[str, int] = {}
_lock = asyncio.Lock()


def _extract_client_ip(websocket: WebSocket) -> str:
    """This stream leans on the client address twice, and both are security decisions.

    It is the `_MAX_PER_IP` cap bucket, and it is the address the operator's
    `ws_allowed_cidrs` allowlist is matched against at the CIDR-whitelist gate
    below. Until B24 was closed everywhere this read the leftmost
    `X-Forwarded-For` entry off any peer, so an off-net client could put an
    allowlisted address in a header it wrote itself and walk through a network
    ACL. The trust rule is shared with every other WS stream; see
    `trusted_ws_client_ip` in ws_discovery.py for what it does and what must not
    be undone.
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

    Same contract, and same reason, as ws_telemetry._unregister. The handler can
    reach this twice for one socket (the receive loop's `finally` always
    unregisters, and the outer `except Exception` unregisters again on its way
    to close(1011)) and can reach it for a socket that was never registered,
    when the failure happened during the auth or CIDR phase. Both used to
    corrupt the tally, because the old body decremented unconditionally and
    treated a count of 0 as `<= 1`: the second call *popped the IP key
    outright*, wiping the count for every other live connection from that
    address and letting it open `_MAX_PER_IP` more. Gating on membership in
    `_connections` — the same set `_register` adds to under the same lock —
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
                # Publisher-side decode failures and client-side send failures
                # shared a handler that broke the loop for both, so one bad
                # payload from any poll worker ended UP/DOWN delivery for a
                # connected dashboard until the user reloaded the page.
                try:
                    data = json.loads(msg["data"])
                    # data carries monitor_id, status, msg, ts (see poll worker).
                    payload = json.dumps(
                        {"type": "monitor_status", "monitor_id": data.get("monitor_id"), **data}
                    )
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
            # to the event loop for up to 1s.
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        # Without the subscription this socket can never report another status
        # change, and a monitor dashboard that shows stale "UP" forever is worse
        # than one that reconnects — close explicitly (REL-07).
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


def _reader_snapshot(user: Any, *, scopes: set[str] | None = None) -> Any:
    """Detach the fields needed for read-scope and legacy-tenant checks."""
    return SimpleNamespace(
        id=getattr(user, "id", None),
        email=getattr(user, "email", None),
        role=getattr(user, "role", "viewer"),
        scopes=json.dumps(sorted(scopes)) if scopes is not None else getattr(user, "scopes", None),
        is_admin=bool(getattr(user, "is_admin", False)),
        is_superuser=bool(getattr(user, "is_superuser", False)),
        is_active=bool(getattr(user, "is_active", True)),
        locked_until=getattr(user, "locked_until", None),
        demo_expires=getattr(user, "demo_expires", None),
        tenant_id=getattr(user, "tenant_id", None),
    )


def _is_reader_active(user: Any) -> bool:
    if not getattr(user, "is_active", False):
        return False
    locked_until = getattr(user, "locked_until", None)
    if locked_until and locked_until > utcnow():
        return False
    demo_expires = getattr(user, "demo_expires", None)
    return not (getattr(user, "role", None) == "demo" and demo_expires and demo_expires <= utcnow())


def _has_monitor_read_scope(reader: Any, token_scopes: set[str] | None = None) -> bool:
    scopes = token_scopes if token_scopes is not None else effective_scopes(reader)
    return has_scope(scopes, "read", "*")


def _normalise_scope_set(raw_scopes: object) -> set[str]:
    if not isinstance(raw_scopes, list):
        return set()
    return {str(scope).strip() for scope in raw_scopes if str(scope).strip()}


def _authenticate_monitor_reader(db: Any, raw_token: str) -> Any | None:
    """Authenticate a monitor stream identity with the HTTP monitor read policy.

    The monitor stream accepts browser session cookies, first-message session
    JWTs, service-account JWTs, and stored API tokens. A successful handshake is
    not enough: the identity must also carry the same ``read:*`` authority that
    HTTP monitor reads require.
    """
    cfg = get_or_create_settings(db)
    if not cfg.auth_enabled:
        return _reader_snapshot(
            SimpleNamespace(
                id=0,
                email="auth-disabled@system",
                role="admin",
                scopes=None,
                is_admin=True,
                is_superuser=True,
                is_active=True,
                locked_until=None,
                demo_expires=None,
                tenant_id=None,
            )
        )
    if not cfg.jwt_secret or not raw_token or is_session_revoked(db, raw_token):
        return None

    try:
        payload = jwt.decode(
            raw_token,
            cfg.jwt_secret,
            algorithms=["HS256"],
            audience=[SESSION_AUDIENCE],
        )
    except (jwt.PyJWTError, ValueError, TypeError):
        payload = None

    if isinstance(payload, dict):
        uid_raw = payload.get("sub", payload.get("user_id"))
        try:
            uid = int(uid_raw) if uid_raw is not None else None
        except (TypeError, ValueError):
            uid = None
        if uid == 0:
            # Same gate as core.security.resolve_optional_user_id_sync: a
            # service-account JWT is live only while its APIToken row is. This
            # branch short-circuits ahead of the scan below, so without the check
            # a revoked or rotated token kept its monitor stream open.
            if not service_account_token_is_live(db, raw_token):
                return None
            token_scopes = _normalise_scope_set(payload.get("scopes"))
            if not _has_monitor_read_scope(
                _reader_snapshot(SimpleNamespace(id=0, role="admin", is_active=True)),
                token_scopes,
            ):
                return None
            return _reader_snapshot(
                SimpleNamespace(
                    id=0,
                    email="api-token@system",
                    role="admin",
                    scopes=None,
                    is_admin=True,
                    is_superuser=True,
                    is_active=True,
                    locked_until=None,
                    demo_expires=None,
                    tenant_id=None,
                ),
                scopes=token_scopes,
            )
        if uid is not None:
            user = db.get(User, uid)
            if user and _is_reader_active(user) and _has_monitor_read_scope(user):
                return _reader_snapshot(user)
            return None

    for candidate in db.query(APIToken).all():
        stored = candidate.token_hash or ""
        if not verify_salted_api_token_hash(raw_token, stored):
            continue
        if candidate.expires_at and candidate.expires_at <= utcnow():
            return None
        user = db.get(User, candidate.created_by)
        token_scopes = _normalise_scope_set(candidate.scopes)
        if user and _is_reader_active(user) and _has_monitor_read_scope(user, token_scopes):
            return _reader_snapshot(user, scopes=token_scopes)
        return None

    return None


def _authorized_monitor_channels(db: Any, reader: Any, monitor_ids: list[Any]) -> set[str]:
    channels: set[str] = set()
    seen: set[int] = set()
    for raw_mid in monitor_ids[:_MAX_SUBSCRIPTIONS]:
        if not isinstance(raw_mid, int) or raw_mid in seen:
            continue
        seen.add(raw_mid)
        monitor = monitor_service.get_monitor(db, raw_mid)
        if monitor and monitor_service.reader_can_access_monitor(db, reader, monitor):
            channels.add(f"monitor:{raw_mid}")
    return channels


async def _ping_loop(ws: WebSocket, main_task: asyncio.Task, raw_token: str) -> None:
    """Keepalive pings, and the only place a live connection re-checks its authority.

    Authenticating at handshake alone meant a revoked session, a deactivated
    user, or a token whose scopes were narrowed kept receiving monitor data for
    as long as it stayed connected — potentially indefinitely. Re-running the
    full handshake policy here bounds that to one ping interval and keeps a
    single definition of who may read this stream.
    """
    try:
        while True:
            await asyncio.sleep(_PING_INTERVAL_SECONDS)
            if ws.application_state == WebSocketState.DISCONNECTED:
                main_task.cancel()
                break
            with _db_session.SessionLocal() as db:
                still_authorized = _authenticate_monitor_reader(db, raw_token) is not None
            if not still_authorized:
                logger.info("Monitor WS closing: session no longer authorized")
                try:
                    await ws.send_text(json.dumps({"error": "session_revoked"}))
                    await ws.close(code=1008)
                except Exception:
                    # Already gone — the receive loop's own disconnect handling
                    # will clean up.
                    pass
                # Deliberately no main_task.cancel(): closing the socket makes
                # the handler's next receive raise WebSocketDisconnect, which it
                # already handles and which runs its cleanup. Cancelling instead
                # propagates CancelledError out through the ASGI app.
                break
            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
    except asyncio.CancelledError:
        pass
    except Exception:
        # Send failed — client disconnected. Cancel the receive loop immediately
        # so the handler's finally block runs without waiting 30s for the next ping.
        main_task.cancel()


@router.websocket("/stream")
async def monitor_stream(websocket: WebSocket) -> None:
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

        reader: Any | None = None

        with _db_session.SessionLocal() as db:
            reader = _authenticate_monitor_reader(db, raw_token)

        if reader is None:
            logger.warning("Monitor WS auth failed (ip=%s)", client_ip)
            await websocket.send_text(json.dumps({"error": "unauthorized"}))
            await websocket.close(code=1008)
            return

        # ── CIDR whitelist ──────────────────────────────────────────────
        with _db_session.SessionLocal() as _ws_db:
            _ws_cfg = get_or_create_settings(_ws_db)
            _ws_cidrs = getattr(_ws_cfg, "ws_allowed_cidrs", "[]") or "[]"
        if not _is_ip_in_cidrs(client_ip, _ws_cidrs):
            logger.warning("Monitor WS rejected by CIDR whitelist (ip=%s)", client_ip)
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
        ping_task = asyncio.create_task(_ping_loop(websocket, _current_task, raw_token))

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
                    monitor_ids = msg["subscribe"]
                    if isinstance(monitor_ids, list):
                        with _db_session.SessionLocal() as db:
                            new_channels = _authorized_monitor_channels(db, reader, monitor_ids)
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
                    monitor_ids = msg["unsubscribe"]
                    if isinstance(monitor_ids, list):
                        for mid in monitor_ids:
                            subscribed_channels.discard(f"monitor:{mid}")
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
        logger.error("Monitor WS unhandled error (ip=%s): %s", client_ip, exc)
        try:
            await _unregister(websocket, client_ip)
            await websocket.close(code=1011)
        except Exception:
            pass
