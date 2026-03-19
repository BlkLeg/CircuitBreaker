"""Status dashboard WebSocket stream.

Clients connect to receive live status updates when the status poll job completes.
Broadcasts are triggered from the status_worker via schedule_status_broadcast().
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.auth_cookie import is_websocket_secure, ws_require_wss
from app.core.time import utcnow_iso
from app.core.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Reuse the same connection limits as discovery/topology via a dedicated manager
status_ws_manager = ConnectionManager()

_main_loop: asyncio.AbstractEventLoop | None = None


def set_status_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from main.py lifespan to allow sync worker to schedule broadcasts."""
    global _main_loop
    _main_loop = loop


def schedule_status_broadcast(payload: dict[str, Any]) -> None:
    """Schedule a broadcast to all status WS clients.

    Safe to call from sync (e.g. status_worker).
    """
    if _main_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            status_ws_manager.broadcast(payload),
            _main_loop,
        )
    except Exception as e:
        logger.warning("Status broadcast schedule failed: %s", e)


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
    except Exception:
        main_task.cancel()


def _extract_client_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


async def status_stream(websocket: WebSocket) -> None:
    """Accept one status stream client; expect JWT in first message."""
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
        raw_token = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
    except TimeoutError:
        await websocket.send_text(json.dumps({"error": "auth_timeout"}))
        await websocket.close(code=1008)
        return
    except WebSocketDisconnect:
        return

    authenticated = False
    user_id: int | None = None
    import app.db.session as _db_session
    from app.core.security import _get_api_token, decode_token
    from app.core.time import utcnow
    from app.db.models import User
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import is_session_revoked

    api_token = _get_api_token()
    if api_token and raw_token.strip() == api_token:
        authenticated = True
        user_id = 0
    else:
        with _db_session.SessionLocal() as db:
            cfg = get_or_create_settings(db)
            if cfg.jwt_secret:
                if not is_session_revoked(db, raw_token.strip()):
                    uid = decode_token(raw_token.strip(), cfg.jwt_secret)
                    if uid is not None:
                        u = db.get(User, uid)
                        if (
                            u
                            and u.is_active
                            and not (u.locked_until is not None and u.locked_until > utcnow())
                        ):
                            authenticated = True
                            user_id = uid

    if not authenticated:
        await websocket.send_text(json.dumps({"error": "unauthorized"}))
        await websocket.close(code=1008)
        return

    accepted = await status_ws_manager.connect(
        websocket,
        user_id=user_id,
        client_ip=client_ip,
    )
    if not accepted:
        await websocket.send_text(json.dumps({"error": "connection_limit_exceeded"}))
        await websocket.close(code=1008)
        return

    await websocket.send_text(json.dumps({"status": "connected", "type": "status_stream"}))

    _current_task = asyncio.current_task()
    assert _current_task is not None
    ping_task = asyncio.create_task(_ping_loop(websocket, _current_task))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw) if raw.strip() else {}
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Status stream receive error")
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass
        await status_ws_manager.disconnect(websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


def status_ws_status_snapshot() -> dict:
    """Return connection metrics for GET /status/ws/status."""
    return status_ws_manager.status_snapshot()


router = APIRouter()


@router.websocket("/stream")
async def ws_status_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for live status updates."""
    await status_stream(websocket)


@router.get("/ws/status")
def ws_status_connections() -> dict:
    """Return status WebSocket connection metrics (admin/debug)."""
    return status_ws_status_snapshot()
