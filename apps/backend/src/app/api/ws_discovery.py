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
- Plain ws:// connections are warned about in production (use WSS).
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import app.db.session as _db_session
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.rbac import require_role
from app.core.security import _get_api_token, decode_token
from app.core.time import utcnow, utcnow_iso
from app.core.ws_manager import ws_manager
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_client_ip(websocket: WebSocket) -> str:
    """Extract real client IP, honouring X-Forwarded-For set by nginx."""
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


def _warn_if_insecure(websocket: WebSocket) -> None:
    """Log a warning when the connection arrives over plain ws:// in production."""
    scheme = websocket.headers.get("x-forwarded-proto", "")
    if scheme and scheme.lower() == "http":
        logger.warning(
            "WS connection over plain HTTP detected from %s — "
            "use HTTPS/WSS in production to protect the auth token.",
            _extract_client_ip(websocket),
        )


async def _ping_loop(ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            if ws.application_state == WebSocketState.DISCONNECTED:
                break
            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f"Ping loop error: {e}")


# NOTE: This router is mounted at prefix /api/v1/discovery in main.py.
# All decorator paths here are relative to that prefix.
@router.websocket("/stream")
async def discovery_stream(websocket: WebSocket) -> None:
    # Always accept first — token auth follows as the first message.
    await websocket.accept()

    if ws_require_wss() and not is_websocket_secure(websocket.scope):
        try:
            await websocket.send_text(json.dumps({"error": "wss_required"}))
            await websocket.close(code=1008)
        except Exception:
            pass
        return

    client_ip = _extract_client_ip(websocket)
    _warn_if_insecure(websocket)

    try:
        # ── Auth phase: cookie (httpOnly) or first message (legacy token) ─────
        raw_token = token_from_websocket_scope(websocket.scope)
        if not raw_token:
            try:
                raw_token = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            except TimeoutError:
                logger.warning("WS auth timeout (ip=%s)", client_ip)
                try:
                    await websocket.send_text(json.dumps({"error": "auth_timeout"}))
                    await websocket.close(code=1008)
                except Exception:
                    pass
                return
            except WebSocketDisconnect:
                return

        authenticated = False
        user_id: int | None = None
        api_token = _get_api_token()

        if api_token and raw_token == api_token:
            authenticated = True
            user_id = 0  # service-account sentinel
        else:
            with _db_session.SessionLocal() as db:
                cfg = get_or_create_settings(db)
                # When auth is disabled, any connection is allowed through.
                if not cfg.auth_enabled:
                    authenticated = True
                    user_id = 0  # anonymous sentinel
                elif cfg.jwt_secret:
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

        # ── Keep-alive + receive loop ───────────────────────────────────────
        ping_task = asyncio.create_task(_ping_loop(websocket))

        try:
            while True:
                raw = await websocket.receive_text()
                # Respond to application-level pings from the client.
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict) and msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
                except Exception:
                    pass  # Unknown / malformed client frames are silently ignored.
        except WebSocketDisconnect:
            pass
        finally:
            ping_task.cancel()
            await ws_manager.disconnect(websocket)

    except Exception as e:
        logger.error("WS unhandled error (ip=%s): %s", client_ip, e)
        try:
            await ws_manager.disconnect(websocket)
            await websocket.close(code=1011)
        except Exception:
            pass


@router.get("/ws/status")
async def ws_status(user=require_role("admin")) -> dict:
    """Admin-facing endpoint: live WebSocket connection metrics."""
    return ws_manager.status_snapshot()
