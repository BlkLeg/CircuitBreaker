"""Agent-facing WebSocket endpoints. /enroll and /link bypass session auth
entirely — the Noise handshake IS their authentication (spec §3.5). /stream
(added in Task 15) is session-authenticated and carries presence to the UI.

No domain logic lives here beyond decode/dispatch — see agent_link.py's
boundary note in specs/2026-07-26-cb-agent-design.md §1.2.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.agent_crypto import (
    ClockSkewError,
    NoiseIKResponder,
    check_clock_skew,
    get_server_static_keypair,
)
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.schemas.agent_frame import TYPE_CAPABILITIES_SET, TYPE_HELLO_ACK, AgentFrame
from app.services import agent_enrollment, agent_link, agent_registry

_logger = logging.getLogger(__name__)

unauthenticated_router = APIRouter()
authenticated_router = APIRouter()

_HANDSHAKE_TIMEOUT_SECONDS = 10.0
_LINK_POLL_SECONDS = 5.0
_LINK_DEAD_SECONDS = 60.0  # three missed 20s heartbeats


def _ack_bytes(responder: NoiseIKResponder, payload: dict) -> bytes:
    frame = {
        "v": 1,
        "type": TYPE_HELLO_ACK,
        "seq": 0,
        "ts": utcnow().isoformat(),
        "payload": payload,
    }
    return responder.encrypt(json.dumps(frame).encode())


def _error_bytes(responder: NoiseIKResponder, error: str) -> bytes:
    return _ack_bytes(responder, {"error": error})


@unauthenticated_router.websocket("/enroll")
async def enroll_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"

    try:
        handshake_msg = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
    except Exception:
        # Broad on purpose: this is the very first frame from an anonymous,
        # adversarial-by-default client. Besides TimeoutError/WebSocketDisconnect,
        # Starlette's receive_bytes() raises a bare KeyError if the client sends a
        # TEXT frame instead of BINARY as its first message (it indexes
        # message["bytes"], which a text frame's message dict doesn't have). Any
        # unexpected shape here degrades to a clean close, never a crash.
        await websocket.close(code=1008)
        return

    server_priv, _ = get_server_static_keypair()
    responder = NoiseIKResponder(server_priv)
    try:
        response = responder.read_message(handshake_msg)
    except Exception:
        _logger.info("agent enroll: handshake failed from %s", client_ip)
        await websocket.close(code=1008)
        return
    await websocket.send_bytes(response)

    try:
        hello_ct = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        hello = json.loads(responder.decrypt(hello_ct))
    except Exception:
        await websocket.close(code=1008)
        return

    try:
        check_clock_skew(datetime.fromisoformat(hello["ts"]).replace(tzinfo=None))
    except ClockSkewError:
        await websocket.send_bytes(_error_bytes(responder, "clock_skew"))
        await websocket.close(code=1008)
        return
    except Exception:
        # A missing "ts" key raises KeyError; a malformed timestamp string raises
        # ValueError from fromisoformat(). Neither is a clock-skew condition, but
        # both are just as reachable by any anonymous client that completes the
        # handshake (no prior registration required), so they get the same clean
        # close as every other malformed-input path in this handler.
        await websocket.close(code=1008)
        return

    payload = hello.get("payload", {})
    device_pk_hex = responder.remote_static().hex()
    fingerprint = hashlib.sha256(bytes.fromhex(device_pk_hex)).hexdigest()[:32]

    with SessionLocal() as db:
        existing = agent_registry.get_agent_by_device_pk(db, device_pk_hex)
        # revoked and rejected both close cleanly with no new row: device_pk is
        # unique, so falling through to create_pending_agent() for either would
        # raise an uncaught IntegrityError on the existing row. Nothing in the
        # spec describes a rejected-agent re-enrollment flow, so — same as
        # revoked — the safer default is to refuse the reconnect rather than
        # invent silent re-enrollment semantics; an operator who wants to let a
        # previously-rejected device retry needs an explicit admin action (reset
        # to pending) that isn't part of this slice.
        if existing is not None and existing.status in ("revoked", "rejected"):
            await websocket.close(code=1008)
            return
        if existing is not None and existing.status == "active":
            await websocket.send_bytes(
                _ack_bytes(responder, {"already_enrolled": True, "status": "active"})
            )
            await websocket.close(code=1000)
            return
        if existing is not None and existing.status == "pending":
            agent = existing
        else:
            agent = agent_registry.create_pending_agent(
                db,
                device_pk=device_pk_hex,
                fingerprint=fingerprint,
                hostname=payload.get("hostname"),
                machine_id_hash=payload.get("machine_id_hash"),
                os=payload.get("os"),
                os_version=payload.get("os_version"),
                arch=payload.get("arch"),
                agent_version=payload.get("agent_version"),
                primary_macs=payload.get("primary_macs"),
                reported_ip=client_ip,
            )
        db.commit()
        agent_id = agent.id
        code = await agent_enrollment.mint_pairing_code(agent_id)

    await websocket.send_bytes(
        _ack_bytes(
            responder,
            {"agent_id": agent_id, "pairing_code": code, "magic_link": f"/agents/enroll?c={code}"},
        )
    )

    # Hold the connection, polling for the approval decision every 2s (fast enough that
    # "click approve, done" in §5.2 doesn't visibly lag) and re-minting the pairing code only
    # when its 15-minute TTL actually lapses.
    _POLL_SECONDS = 2.0
    last_minted_at = utcnow()
    while True:
        try:
            await asyncio.wait_for(websocket.receive_bytes(), timeout=_POLL_SECONDS)
        except TimeoutError:
            with SessionLocal() as db:
                fresh = agent_registry.get_agent(db, agent_id)
                if fresh is None:
                    break
                if fresh.status != "pending":
                    await websocket.send_bytes(
                        _ack_bytes(responder, {"agent_id": agent_id, "status": fresh.status})
                    )
                    await websocket.close(code=1000)
                    return
                elapsed = (utcnow() - last_minted_at).total_seconds()
                if elapsed >= agent_enrollment.PAIRING_CODE_TTL_SECONDS:
                    code = await agent_enrollment.mint_pairing_code(agent_id)
                    last_minted_at = utcnow()
                    await websocket.send_bytes(
                        _ack_bytes(responder, {"agent_id": agent_id, "pairing_code": code})
                    )
        except WebSocketDisconnect:
            break


def _capabilities_bytes(responder: NoiseIKResponder, grants: dict[str, bool]) -> bytes:
    frame = {
        "v": 1,
        "type": TYPE_CAPABILITIES_SET,
        "seq": 0,
        "ts": utcnow().isoformat(),
        "payload": grants,
    }
    return responder.encrypt(json.dumps(frame).encode())


@unauthenticated_router.websocket("/link")
async def link_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        handshake_msg = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
    except Exception:
        # Same broad catch as enroll_stream — an anonymous, adversarial-by-default
        # client can send anything as its first frame.
        await websocket.close(code=1008)
        return

    server_priv, _ = get_server_static_keypair()
    responder = NoiseIKResponder(server_priv)
    try:
        response = responder.read_message(handshake_msg)
    except Exception:
        await websocket.close(code=1008)
        return
    await websocket.send_bytes(response)

    device_pk_hex = responder.remote_static().hex()
    with SessionLocal() as db:
        agent = agent_registry.get_agent_by_device_pk(db, device_pk_hex)
        if agent is None or agent.status != "active":
            await websocket.close(code=1008)
            return
        agent_id = agent.id
        grants = agent_registry.grants_dict(db, agent_id)
        agent_registry.record_event(db, agent_id, "connected")
        db.commit()

    worker = socket.gethostname()
    await agent_registry.mark_presence_connected(agent_id, worker=worker)
    await websocket.send_bytes(_capabilities_bytes(responder, grants))

    last_activity = utcnow()
    try:
        while True:
            try:
                ct = await asyncio.wait_for(websocket.receive_bytes(), timeout=_LINK_POLL_SECONDS)
            except TimeoutError:
                if (utcnow() - last_activity).total_seconds() >= _LINK_DEAD_SECONDS:
                    break
                with SessionLocal() as db:
                    fresh = agent_registry.get_agent(db, agent_id)
                    if fresh is None or fresh.status != "active":
                        break
                continue
            except WebSocketDisconnect:
                break

            last_activity = utcnow()
            try:
                pt = responder.decrypt(ct)
                agent_frame = AgentFrame.model_validate_json(pt)
            except Exception:
                continue

            with SessionLocal() as db:
                fresh = agent_registry.get_agent(db, agent_id)
                if fresh is None or fresh.status != "active":
                    break
                await agent_link.dispatch_frame(db, fresh, agent_frame)
    finally:
        await agent_registry.mark_presence_disconnected(agent_id)
        with SessionLocal() as db:
            agent_registry.record_event(db, agent_id, "disconnected")
            db.commit()
