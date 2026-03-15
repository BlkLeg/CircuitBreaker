"""
Topology WebSocket stream.

Endpoint: WS /api/v1/topology/stream

Delivers real-time topology events to connected clients (MapPage, rack views).
Events are broadcast by the NATS → WebSocket bridge in main.py when any of the
following subjects are received:
  - topology.node.moved          → {"type": "node_moved", ...}
  - topology.cable.added         → {"type": "cable_added", ...}
  - topology.cable.removed       → {"type": "cable_removed", ...}
  - topology.node.status_changed → {"type": "node_status_changed", ...}

Auth protocol (identical to ws_discovery.py):
  1. Client connects.
  2. Server waits up to 10 seconds for the first text message.
  3. First message must be a valid JWT token (raw string).
  4. On failure: sends {"error": "unauthorized"} and closes with code 1008.
  5. On success: sends {"status": "connected"} and begins streaming events.

Client → server messages:
  {"type": "ping"}  → server responds with {"type": "pong", "ts": "<utc iso>"}

The server sends a ping every 30 seconds for keep-alive.
"""

import asyncio
import hmac
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.rbac import require_role
from app.core.security import _get_api_token, decode_token
from app.core.time import utcnow, utcnow_iso
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_CONNECTIONS: int = int(os.getenv("CB_WS_TOPO_MAX_CONNECTIONS", "50"))
_MAX_PER_IP: int = int(os.getenv("CB_WS_TOPO_MAX_PER_IP", "5"))


class TopologyConnectionManager:
    """WebSocket connection manager for topology stream clients."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._meta: dict[WebSocket, dict] = {}
        self._ip_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._buffer: list[dict] = []
        self._batch_lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._buffer: list[dict] = []  # type: ignore[no-redef]
        self._batch_lock = asyncio.Lock()  # type: ignore[no-redef]

    async def connect(
        self,
        ws: WebSocket,
        *,
        user_id: int | None = None,
        client_ip: str = "unknown",
    ) -> bool:
        async with self._lock:
            if len(self._connections) >= _MAX_CONNECTIONS:
                logger.warning(
                    "Topology WS rejected: global cap %d reached (ip=%s)",
                    _MAX_CONNECTIONS,
                    client_ip,
                )
                return False
            if self._ip_counts.get(client_ip, 0) >= _MAX_PER_IP:
                logger.warning(
                    "Topology WS rejected: per-IP cap %d reached (ip=%s)",
                    _MAX_PER_IP,
                    client_ip,
                )
                return False

            self._connections.add(ws)
            self._meta[ws] = {
                "user_id": user_id,
                "ip": client_ip,
                "connected_at": utcnow_iso(),
            }
            self._ip_counts[client_ip] = self._ip_counts.get(client_ip, 0) + 1
            logger.info(
                "Topology WS connected (user=%s ip=%s total=%d)",
                user_id,
                client_ip,
                len(self._connections),
            )
            return True

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            meta = self._meta.pop(ws, None)
            if meta:
                ip = meta.get("ip", "unknown")
                current = self._ip_counts.get(ip, 0)
                if current <= 1:
                    self._ip_counts.pop(ip, None)
                else:
                    self._ip_counts[ip] = current - 1
                logger.info(
                    "Topology WS disconnected (user=%s ip=%s remaining=%d)",
                    meta.get("user_id"),
                    ip,
                    len(self._connections),
                )

    async def _flush_buffer(self):
        async with self._batch_lock:
            if not self._buffer:
                self._flush_task = None
                return
            batch = self._buffer[:]
            self._buffer.clear()
            self._flush_task = None

        payload = json.dumps({"type": "batch", "events": batch})
        async with self._lock:
            snapshot = list(self._connections)

        dead: list[WebSocket] = []
        for ws in snapshot:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.debug("Topology WS send failed: %s", e, exc_info=True)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
                    meta = self._meta.pop(ws, None)
                    if meta:
                        ip = meta.get("ip", "unknown")
                        current = self._ip_counts.get(ip, 0)
                        if current <= 1:
                            self._ip_counts.pop(ip, None)
                        else:
                            self._ip_counts[ip] = current - 1

    async def broadcast(self, message: dict) -> None:
        async with self._batch_lock:
            self._buffer.append(message)
            if len(self._buffer) >= 50:
                if getattr(self, "_flush_task", None):
                    self._flush_task.cancel()  # type: ignore[union-attr]
                self._flush_task = asyncio.create_task(self._flush_buffer())
                return

        async def _delayed_flush():
            await asyncio.sleep(0.250)
            await self._flush_buffer()

        async with self._batch_lock:
            if len(self._buffer) == 1:
                self._flush_task = asyncio.create_task(_delayed_flush())

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def status_snapshot(self) -> dict:
        return {
            "connections": len(self._connections),
            "max_connections": _MAX_CONNECTIONS,
            "max_per_ip": _MAX_PER_IP,
            "ip_counts": dict(self._ip_counts),
        }


topology_ws_manager = TopologyConnectionManager()


def _extract_client_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


async def _ping_loop(ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            if ws.application_state == WebSocketState.DISCONNECTED:
                break
            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
    except asyncio.CancelledError:
        logger.debug("Topology ping loop cancelled during connection shutdown")
    except Exception as exc:
        logger.debug("Topology WS ping loop error: %s", exc)


@router.websocket("/stream")
async def topology_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(dict(websocket.scope)):
        try:
            await websocket.send_text(json.dumps({"error": "wss_required"}))
            await websocket.close(code=1008)
        except Exception as e:
            logger.debug("Topology WS wss_required close failed: %s", e, exc_info=True)
        return

    client_ip = _extract_client_ip(websocket)

    try:
        # ── Auth phase: cookie (httpOnly) only ──────────────────────────────
        raw_token = token_from_websocket_scope(dict(websocket.scope))
        if not raw_token:
            logger.warning("Topology WS auth rejected: no session cookie (ip=%s)", client_ip)
            try:
                await websocket.send_text(json.dumps({"error": "unauthorized"}))
                await websocket.close(code=1008)
            except Exception as exc:
                logger.debug("Failed to send auth error to client (already disconnected): %s", exc)
            return

        authenticated = False
        user_id: int | None = None
        api_token = _get_api_token()

        if api_token and raw_token and hmac.compare_digest(raw_token, api_token):
            authenticated = True
            user_id = 0
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
                                        user_id = uid

        if not authenticated:
            logger.warning("Topology WS auth failed (ip=%s)", client_ip)
            try:
                await websocket.send_text(json.dumps({"error": "unauthorized"}))
                await websocket.close(code=1008)
            except Exception as e:
                logger.debug("Topology WS unauthorized close failed: %s", e, exc_info=True)
            return

        # ── Connection cap check ────────────────────────────────────────────
        accepted = await topology_ws_manager.connect(
            websocket, user_id=user_id, client_ip=client_ip
        )
        if not accepted:
            try:
                await websocket.send_text(json.dumps({"error": "connection_limit_exceeded"}))
                await websocket.close(code=1008)
            except Exception as e:
                logger.debug("Topology WS limit close failed: %s", e, exc_info=True)
            return

        await websocket.send_text(json.dumps({"status": "connected"}))

        # ── Keep-alive + receive loop ───────────────────────────────────────
        ping_task = asyncio.create_task(_ping_loop(websocket))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict) and msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
                except Exception as e:
                    logger.debug("Topology WS ping parse/send failed: %s", e, exc_info=True)
        except WebSocketDisconnect:
            logger.debug("Topology WebSocket disconnected normally")
        finally:
            ping_task.cancel()
            await topology_ws_manager.disconnect(websocket)

    except Exception as exc:
        logger.error("Topology WS unhandled error (ip=%s): %s", client_ip, exc)
        try:
            await topology_ws_manager.disconnect(websocket)
            await websocket.close(code=1011)
        except Exception as e:
            logger.debug("Topology WS error cleanup close failed: %s", e, exc_info=True)


@router.get("/ws/status")
async def topology_ws_status(user=require_role("admin")) -> dict:
    """Admin-facing endpoint: live topology WebSocket connection metrics."""
    return topology_ws_manager.status_snapshot()
