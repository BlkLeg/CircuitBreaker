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

The server sends a ping every 30 seconds to keep the connection alive.
Clients should reconnect on unexpected close.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.security import decode_token, _get_api_token
from app.core.ws_manager import ws_manager
import app.db.session as _db_session
from app.services.settings_service import get_or_create_settings
from app.core.time import utcnow_iso

logger = logging.getLogger(__name__)

router = APIRouter()


async def _ping_loop(ws: WebSocket):
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


@router.websocket("/api/v1/discovery/stream")
async def discovery_stream(websocket: WebSocket):
    await websocket.accept()

    try:
        # Wait for auth token
        raw_token = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        
        # Verify Token — always required regardless of auth_enabled
        authenticated = False
        api_token = _get_api_token()

        if api_token and raw_token == api_token:
            authenticated = True
        else:
            with _db_session.SessionLocal() as db:
                cfg = get_or_create_settings(db)
                if cfg.jwt_secret:
                    user_id = decode_token(raw_token, cfg.jwt_secret)
                    if user_id is not None:
                        authenticated = True
        if not authenticated:
            await websocket.send_text(json.dumps({"error": "unauthorized"}))
            await websocket.close(code=1008)
            return
            
        await websocket.send_text(json.dumps({"status": "connected"}))
        await ws_manager.connect(websocket)
        
        # Start ping loop
        ping_task = asyncio.create_task(_ping_loop(websocket))

        try:
            while True:
                # Keep connection alive and listen for client messages (if any)
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ping_task.cancel()
            ws_manager.disconnect(websocket)

    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="Auth timeout")
    except WebSocketDisconnect:
        # Client disconnected before auth completed — socket was never registered
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            ws_manager.disconnect(websocket)
            await websocket.close(code=1011)
        except Exception:
            pass
