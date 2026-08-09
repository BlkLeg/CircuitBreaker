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
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import text
from starlette.websockets import WebSocketState

from app.core import agent_crypto
from app.core.agent_crypto import (
    REKEY_DIRECTION_OUTBOUND,
    ClockSkewError,
    NoiseIKResponder,
    RekeyError,
    check_clock_skew,
)
from app.core.auth_cookie import is_websocket_secure, token_from_websocket_scope, ws_require_wss
from app.core.security import decode_token
from app.core.time import utcnow, utcnow_iso
from app.db.models import User
from app.db.session import SessionLocal
from app.schemas.agent_frame import (
    TYPE_CAPABILITIES_SET,
    TYPE_DISCONNECT,
    TYPE_HEARTBEAT,
    TYPE_HELLO_ACK,
    TYPE_KEY_ROTATE,
    TYPE_PING,
    TYPE_TRANSPORT_REKEY,
    TYPE_UPDATE,
    HelloPayload,
    TransportRekeyPayload,
)
from app.services import (
    agent_discovery,
    agent_enrollment,
    agent_link,
    agent_registry,
    agent_update,
)
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked

_logger = logging.getLogger(__name__)

# Slice 3 D-16: an agent's assigned monitors become due again the moment it
# reconnects — but jittered, never all at `now()`. An agent with 300 assignments
# waking up at exactly the same instant gets a whole per-vantage batch claimed on
# the very next scheduler tick and dispatched into a bounded queue, turning a
# healthy reconnect into a burst of capacity-exhausted execution errors. The
# window is `least(interval_secs, 30)` so a fast monitor is not delayed past its
# own interval; the idiom is the one `services/monitoring/scheduler.py` already
# uses for its post-downtime spread.
#
# Runs inside the same `with SessionLocal() as db:` block that records the
# "connected" event, so a connection that fails before that commit leaves the
# schedule untouched.
_REMOTE_PROBE_RECONNECT_SQL = text(
    """
    UPDATE monitor_items
    SET next_due_at = now() + make_interval(secs => random() * least(interval_secs, 30))
    WHERE probe_agent_id = :agent_id AND enabled
    """
)

unauthenticated_router = APIRouter()
authenticated_router = APIRouter()

_HANDSHAKE_TIMEOUT_SECONDS = 10.0
_LINK_POLL_SECONDS = 5.0
_LINK_DEAD_SECONDS = 60.0  # three missed 20s heartbeats
_LINK_PING_INTERVAL_SECONDS = 20.0  # matches the agent's own heartbeatInterval
_STREAM_AUTH_TIMEOUT_SECONDS = 10.0


def _ack_bytes(responder: NoiseIKResponder, payload: dict, seq: int = 0) -> bytes:
    """Wire-encode one `hello.ack` frame.

    Used both by `enroll_stream` (pairing-code/status payloads, always at
    `seq=0` since that socket has no outbound sequence counter of its own)
    and by `link_stream` (the real `HelloAckPayload` shape — accepted,
    agent_id, capabilities, server_time — at whatever `seq` its
    `_OutboundSeq` counter is on).
    """
    frame = {
        "v": 1,
        "type": TYPE_HELLO_ACK,
        "seq": seq,
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

    # Task 21: per-IP + global attempt-rate gate, checked before any Noise
    # handshake byte is read. A bare close with no payload — this endpoint
    # has no cipher to send an encrypted error frame under yet, and even a
    # plaintext reason would leak which limit tripped to an anonymous,
    # adversarial-by-default caller. 1013 ("Try Again Later") signals
    # "rate limited, retry later" without distinguishing per-IP, global, or
    # (further below) the concurrent-pending-enrollment cap.
    if not await agent_enrollment.check_and_record_ws_attempt("enroll", client_ip):
        await websocket.close(code=1013)
        return

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

    # Task 28: tries the server's current identity key first, then (only
    # while a server-key rotation's overlap window is still open) its
    # successor — see agent_crypto.complete_ik_handshake's docstring.
    with SessionLocal() as db:
        handshake_result = agent_crypto.complete_ik_handshake(handshake_msg, db)
    if handshake_result is None:
        _logger.info("agent enroll: handshake failed from %s", client_ip)
        await websocket.close(code=1008)
        return
    responder, response, server_key_kind = handshake_result
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
        pending_lock_token = None
        try:
            if existing is not None and existing.status == "pending":
                agent = existing
                newly_created = False
            else:
                # Task 21: concurrent-pending-enrollment cap. Only guards the
                # genuinely-new-row path — a device_pk already pending (the
                # branch above) is reusing an existing row, not adding to the
                # count, so it's never blocked by this check.
                #
                # The count-then-insert-then-commit sequence below is wrapped in
                # a cross-worker Redis lock (fix round, Important #1): two
                # /enroll connections on different workers could otherwise both
                # read `count_pending_agents` before either committed, both see
                # a count under the cap, and both insert — overshooting it. The
                # lock is held until *after* `db.commit()` further down, not
                # just past the count check, since the race is only actually
                # closed once the new row is durably visible to the next
                # session's count query — see acquire_pending_enrollment_lock's
                # docstring for why this is a lock, not a Redis gauge.
                #
                # Everything from here through db.commit() below runs inside
                # this try, whose finally always releases the lock (fix round
                # 2): create_pending_agent's db.flush() — e.g. a same-device_pk
                # race that slips past the `existing is None` check above,
                # since that read happens before this lock is even acquired —
                # or db.commit() itself can raise, and without the finally the
                # lock would otherwise sit held for its full TTL on every such
                # failure, wrongly rejecting unrelated new enrollments in the
                # meantime.
                pending_lock_token = await agent_registry.acquire_pending_enrollment_lock()
                if pending_lock_token is None:
                    await websocket.close(code=1013)
                    return
                pending_count = agent_registry.count_pending_agents(db)
                if pending_count >= agent_registry.MAX_CONCURRENT_PENDING_AGENTS:
                    await websocket.close(code=1013)
                    return
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
                newly_created = True
            # Task 28: which of the server's two overlapping identity keys
            # this handshake actually authenticated against — see
            # agent_registry.record_server_key_pin's docstring.
            agent_registry.record_server_key_pin(db, agent, server_key_kind)
            db.commit()
        finally:
            if pending_lock_token is not None:
                await agent_registry.release_pending_enrollment_lock(pending_lock_token)
        agent_id = agent.id
        code = await agent_enrollment.mint_pairing_code(agent_id)

    if newly_created:
        # Immediate push to every live /api/agents/stream viewer (the
        # add-agent panel), mirroring the connected/disconnected broadcasts
        # elsewhere in this module — without this, a brand-new pending
        # enrollment is invisible to the UI until its next 30s poll. Only
        # fired for a genuinely new row: a device retrying the /enroll
        # handshake while its prior enrollment is still pending (the
        # `existing.status == "pending"` branch above) reuses that same
        # already-announced row, so re-broadcasting here would be a
        # duplicate "new agent" event for something the UI already knows
        # about.
        await agent_registry.broadcast_presence(agent_id, "enrolled")

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


def _wire_grants(grants: dict[str, Any], capability_schema: int) -> dict[str, Any]:
    if capability_schema >= 2:
        return grants
    return {
        name: value if isinstance(value, bool) else bool(value.get("enabled"))
        for name, value in grants.items()
    }


def _capabilities_bytes(
    responder: NoiseIKResponder, grants: dict[str, Any], seq: int, capability_schema: int = 1
) -> bytes:
    frame = {
        "v": 1,
        "type": TYPE_CAPABILITIES_SET,
        "seq": seq,
        "ts": utcnow().isoformat(),
        "payload": _wire_grants(grants, capability_schema),
    }
    return responder.encrypt(json.dumps(frame).encode())


def _key_rotate_bytes(
    responder: NoiseIKResponder, successor_pk_hex: str, expiry: datetime, seq: int
) -> bytes:
    """Wire-encode one server -> agent `key.rotate` (kind="server") frame —
    Task 28's advertisement of an in-progress rotation's successor identity
    key. Sent unconditionally on every accepted hello.ack for as long as a
    rotation is active (see link_stream's call site), mirroring Task 11's
    "re-send the authoritative [capabilities] set on every hello.ack": this
    is the durability fallback for `agent_registry.broadcast_server_key_rotate`'s
    live push — a connection this worker didn't hold at push time, or one
    that hadn't finished establishing yet, still learns the successor key the
    moment it completes its own hello.ack exchange, live push or not.
    """
    frame = {
        "v": 1,
        "type": TYPE_KEY_ROTATE,
        "seq": seq,
        "ts": utcnow().isoformat(),
        "payload": {
            "kind": "server",
            "successor_pk": successor_pk_hex,
            "expiry": expiry.isoformat(),
        },
    }
    return responder.encrypt(json.dumps(frame).encode())


class _OutboundSeq:
    """Per-connection strictly-increasing sequence counter for frames the
    server sends down one /link session (capabilities.set, update, ...),
    mirroring the agent's own per-session `seq` counter in
    internal/link/link.go. Starts at 0, like the agent's hello frame."""

    def __init__(self) -> None:
        self._next = 0

    def next(self) -> int:
        value = self._next
        self._next += 1
        return value


async def _send_transport_rekey(
    websocket: WebSocket, responder: NoiseIKResponder, seq: int
) -> None:
    """Announce and then apply one server->agent cipher rekey.

    The announcement is encrypted under the *old* send key and only then does
    the cipher rotate — the agent has to be able to decrypt the very frame
    that tells it to rekey. Its mirror image is `sendRekey` in
    apps/agent/internal/link/link.go.
    """
    frame = {
        "v": 1,
        "type": TYPE_TRANSPORT_REKEY,
        "seq": seq,
        "ts": utcnow().isoformat(),
        "payload": {
            "direction": REKEY_DIRECTION_OUTBOUND,
            "generation": responder.next_send_generation,
        },
    }
    await websocket.send_bytes(responder.encrypt(json.dumps(frame).encode()))
    generation = responder.next_send_generation
    responder.rekey_send()
    # Diagnostic only — no key material, just a generation counter — mirrors
    # link.go's own sendRekey log line and is the only externally-observable
    # signal that a rekey happened at all, which the Docker E2E harness
    # (apps/agent/e2e) greps for.
    _logger.info("agent link: performed outbound transport.rekey (generation %d)", generation)


async def _send_ping(websocket: WebSocket, responder: NoiseIKResponder, seq: int) -> None:
    """Active WS-protocol-level liveness probe, sent on its own cadence.

    Distinct from the application `heartbeat` frame the agent sends
    unprompted on its own 20s ticker: this actively nudges the agent rather
    than only ever passively waiting on its heartbeat. It's the server-side
    counterpart of the agent's `case frame.TypePing` handling in
    apps/agent/internal/link/link.go, which replies with an immediate
    heartbeat. It does *not* itself refresh presence or the dead-connection
    deadline — only a genuine inbound `heartbeat` frame does that (see
    `link_stream`'s `last_heartbeat_at`); a ping is a request for a
    heartbeat, not a substitute for one.
    """
    frame = {
        "v": 1,
        "type": TYPE_PING,
        "seq": seq,
        "ts": utcnow().isoformat(),
        "payload": {},
    }
    await websocket.send_bytes(responder.encrypt(json.dumps(frame).encode()))


def _control_frame_bytes(responder: NoiseIKResponder, claimed: dict, seq: int) -> bytes | None:
    """Wire-encode one control-plane frame claimed via the Task 8 registry
    (`agent_registry.claim_agent_control_frames`) for immediate delivery down
    this /link connection.

    `claimed` is whatever `agent_registry.publish_agent_control_frame`'s
    caller published — `{"type": <frame type>, "payload": {...}}` by
    convention (`payload` optional). This is intentionally generic over
    `type`: it doesn't validate against CAPABILITY_FOR_TYPE or otherwise
    special-case capabilities.set/update/disconnect/key.rotate/ping — any of
    those (and any future control frame type) rides the same envelope, same
    as the connect-time `_capabilities_bytes` and the poll-fallback
    `update_frame` in `link_stream` below already do by hand for their one
    frame type each. A malformed claim (missing/blank "type") is dropped
    rather than raising, mirroring `agent_link.receive_frame`'s tolerance of
    malformed input on the inbound side — a bad publish must not take the
    connection down.
    """
    frame_type = claimed.get("type")
    if not isinstance(frame_type, str) or not frame_type.strip():
        _logger.warning("dropping malformed claimed control frame (no type): %r", claimed)
        return None
    frame = {
        "v": 1,
        "type": frame_type,
        "seq": seq,
        "ts": utcnow().isoformat(),
        "payload": claimed.get("payload") or {},
    }
    return responder.encrypt(json.dumps(frame).encode())


async def _run_control_frame_listener(
    agent_id: int, queue: asyncio.Queue[dict], *, worker_id: str
) -> None:
    """Background task: claims control-plane frames published for `agent_id`
    via the Task 8 registry (`agent_registry.claim_agent_control_frames`) and
    hands each to `queue` for `link_stream`'s main loop to encrypt and send.

    `worker_id` must be the same per-connection value `link_stream` passed to
    `register_agent_connection` — `claim_agent_control_frames` only yields
    frames while `worker_id` is still registered as `agent_id`'s connection
    owner, so a mismatch here would silently starve delivery for the whole
    life of the connection.

    Deliberately does *not* touch the websocket, `responder`, or the
    connection's `_OutboundSeq` itself — those are the main loop's alone, so
    there is exactly one place that ever advances the Noise send cipher or
    writes to the socket, and a claimed control frame can never race a
    directly-handled one (rekey/ping/poll-fallback update) for the send
    slot. Mirrors `_redis_agent_listener`'s task-per-connection shape for
    `/stream`, but hands frames off via a queue instead of sending directly,
    for that reason.
    """
    try:
        async for frame in agent_registry.claim_agent_control_frames(agent_id, worker_id=worker_id):
            await queue.put(frame)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _logger.warning("agent %s: control frame listener error: %s", agent_id, exc)


@unauthenticated_router.websocket("/link")
async def link_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"

    # Task 21: same attempt-rate gate as enroll_stream, before any Noise
    # handshake byte is read — see its comment for the close-code rationale.
    if not await agent_enrollment.check_and_record_ws_attempt("link", client_ip):
        await websocket.close(code=1013)
        return

    try:
        handshake_msg = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
    except Exception:
        # Same broad catch as enroll_stream — an anonymous, adversarial-by-default
        # client can send anything as its first frame.
        await websocket.close(code=1008)
        return

    # Task 28: tries the server's current identity key first, then (only
    # while a server-key rotation's overlap window is still open) its
    # successor — see agent_crypto.complete_ik_handshake's docstring.
    with SessionLocal() as db:
        handshake_result = agent_crypto.complete_ik_handshake(handshake_msg, db)
    if handshake_result is None:
        await websocket.close(code=1008)
        return
    responder, response, server_key_kind = handshake_result
    await websocket.send_bytes(response)

    try:
        hello_ct = await asyncio.wait_for(
            websocket.receive_bytes(), timeout=_HANDSHAKE_TIMEOUT_SECONDS
        )
        hello = json.loads(responder.decrypt(hello_ct))
        check_clock_skew(datetime.fromisoformat(hello["ts"]).replace(tzinfo=None))
    except ClockSkewError:
        await websocket.send_bytes(_error_bytes(responder, "clock_skew"))
        await websocket.close(code=1008)
        return
    except Exception:
        await websocket.close(code=1008)
        return

    device_pk_hex = responder.remote_static().hex()
    with SessionLocal() as db:
        # Task 27: resolves against `agent.device_pk` OR an unexpired
        # `agent.pending_device_pk` — see agent_crypto.device_identity_matches
        # for why a Noise IK handshake can never reject an unrecognized key on
        # its own, and resolve_agent_for_handshake's own docstring for why
        # this replaces get_agent_by_device_pk here specifically (not in
        # enroll_stream, which has no rotation concept).
        agent = agent_registry.resolve_agent_for_handshake(db, device_pk_hex)
        if agent is None or agent.status != "active":
            await websocket.close(code=1008)
            return
        agent_id = agent.id
        # Promotes a first successful link under a rotation's pending key, or
        # lazily clears an expired one reconnecting on the still-current key —
        # see settle_device_key_rotation's docstring. A no-op when no
        # rotation is in progress (the common case).
        agent_registry.settle_device_key_rotation(db, agent, device_pk_hex)
        # Task 28: which of the server's two overlapping identity keys this
        # handshake actually authenticated against — see
        # agent_registry.record_server_key_pin's docstring.
        agent_registry.record_server_key_pin(db, agent, server_key_kind)
        # Task 28: read once per connection, alongside everything else this
        # block already reads from `db` — used below (after hello.ack /
        # capabilities.set) to decide whether to also resend the active
        # rotation's key.rotate frame, the durability fallback for
        # agent_registry.broadcast_server_key_rotate's live push.
        rotation_state = agent_crypto.load_server_key_rotation_state(db)
        capability_schema = 1
        # Slice 4 D-16: a hello whose `networks` moved the agent's scope closes
        # the dispatches that scope no longer authorizes. `update_hello_metadata`
        # hands the closed rows back inert and this block publishes them below,
        # after `db.commit()` — every other write in this block could otherwise
        # roll the closure back after the agent had already been told to stop.
        hello_cancellation = agent_discovery.DiscoveryCancellation()
        try:
            hello_payload = HelloPayload.model_validate(hello.get("payload", {}))
        except ValidationError as exc:
            # Malformed metadata in an otherwise-valid, otherwise-accepted
            # hello isn't fatal to the link — every field is optional and
            # this connection has already cleared handshake + device-pk
            # lookup. Just skip the row refresh for this hello rather than
            # tearing down the connection over metadata alone.
            _logger.warning("agent %s: malformed hello payload: %s", agent_id, exc)
        else:
            capability_schema = hello_payload.capability_schema
            hello_cancellation = agent_registry.update_hello_metadata(db, agent, hello_payload)
        grants = agent_registry.structured_grants_dict(db, agent_id)
        agent_registry.record_event(db, agent_id, "connected")
        db.execute(_REMOTE_PROBE_RECONNECT_SQL, {"agent_id": agent_id})
        db.commit()

    # The commit above is what makes the closures durable, so this is the
    # earliest point the agent may be told about them. Never raises (see
    # `publish_discovery_cancels`), and a no-op when the hello moved no scope,
    # which is every reconnect that reports the interfaces it reported before.
    await agent_discovery.publish_discovery_cancels(hello_cancellation)

    worker = socket.gethostname()
    await agent_registry.mark_presence_connected(agent_id, worker=worker)
    # Distinct from the presence "worker" label above: register_agent_connection
    # records this *connection's* ownership of agent_id's live socket, which
    # is what a later worker's control-frame publish (Task 9) resolves
    # against to route delivery here. See agent_registry.WORKER_ID's docstring
    # for why the "worker" label and this aren't the same identifier.
    #
    # The registered value is `connection_id`, not the bare process-wide
    # WORKER_ID: cb-agent uninstall's one-shot notifier (internal/link/
    # link.go's `Uninstall`) deliberately opens a *second* /link connection
    # for an agent whose persistent daemon connection is often still live
    # (runUninstall notifies before it stops the service). On a single
    # worker process both connections would share the identical WORKER_ID,
    # so a bare-WORKER_ID compare-and-delete on disconnect (deregister_
    # agent_connection) couldn't tell them apart — the short-lived second
    # connection's teardown would evict the first, still-live connection's
    # entry. Suffixing WORKER_ID with a per-connection id keeps WORKER_ID's
    # cross-worker meaning (still a prefix, for operator traceability) while
    # making ownership unique per socket, not per process.
    connection_id = f"{agent_registry.WORKER_ID}:{uuid.uuid4().hex[:12]}"
    await agent_registry.register_agent_connection(agent_id, worker_id=connection_id)
    await agent_registry.broadcast_presence(agent_id, "connected")
    outbound_seq = _OutboundSeq()
    # A genuine `hello.ack` — accepted, this agent's id, the complete current
    # grant set, and server_time (HelloAckPayload, Task 1) — must go out
    # first: the real Go agent (apps/agent/internal/link/link.go) only fires
    # OnConnected (resets reconnect backoff, gates link success — Task 4)
    # from its `case frame.TypeHelloAck` branch when `Accepted` is true.
    # Before this, /link never sent a `hello.ack` frame at all, so that
    # gating logic could never actually fire in production. Task 1's
    # HelloAckPayload doc comment ("the server re-sends the authoritative
    # set on every hello.ack") is why the full grants dict rides along here
    # too, not just capabilities.set below — this is the durable-delivery
    # half of Task 11: a missed capabilities.set push (Task 9's cross-worker
    # delivery) is corrected the moment the agent's next reconnect completes
    # this same hello.ack exchange, independent of push success/failure.
    #
    # The capabilities.set frame right after is left in place alongside it,
    # not replaced by it: today's Go agent only ever applies grants via its
    # `OnCapabilitiesSet` callback (fired on `case frame.TypeCapabilitiesSet`
    # — see link.go), never by reading HelloAckPayload.Capabilities off the
    # hello.ack itself, so it's still needed for the grants to actually take
    # effect on connect.
    await websocket.send_bytes(
        _ack_bytes(
            responder,
            {
                "accepted": True,
                "agent_id": agent_id,
                "server_time": utcnow().isoformat(),
                "capabilities": _wire_grants(grants, capability_schema),
            },
            outbound_seq.next(),
        )
    )
    await websocket.send_bytes(
        _capabilities_bytes(responder, grants, outbound_seq.next(), capability_schema)
    )
    # Task 28: resend the active rotation's key.rotate (kind="server") frame
    # on every accepted hello.ack, exactly like capabilities.set above —
    # the durability fallback for agent_registry.broadcast_server_key_rotate's
    # live push (see _key_rotate_bytes' docstring). A no-op the overwhelming
    # majority of the time (no rotation in progress).
    if rotation_state.rotation_active:
        assert rotation_state.successor_pub is not None
        assert rotation_state.overlap_expires_at is not None
        await websocket.send_bytes(
            _key_rotate_bytes(
                responder,
                rotation_state.successor_pub.hex(),
                rotation_state.overlap_expires_at,
                outbound_seq.next(),
            )
        )

    # Task 9: listen for control-plane frames (capabilities.set, update,
    # disconnect, key.rotate, ping — whatever a REST/service-layer caller
    # publishes via agent_registry.publish_agent_control_frame, potentially
    # from a *different* worker process than this one) claimed for this
    # connection's agent_id, for as long as this worker holds the
    # connection. Cancelled in the `finally` block below alongside the rest
    # of this connection's teardown.
    control_queue: asyncio.Queue[dict] = asyncio.Queue()
    control_task = asyncio.create_task(
        _run_control_frame_listener(agent_id, control_queue, worker_id=connection_id)
    )

    # last_heartbeat_at is the WS-level read deadline's clock — deliberately
    # *not* "last time any frame arrived". It only ever advances on a valid
    # inbound `heartbeat` frame (below), so a run of other traffic (a
    # transport.rekey announcement, a log frame, a stray malformed frame)
    # can never mask a stalled agent heartbeat and keep a hung connection
    # alive: _LINK_DEAD_SECONDS is measured from the last real heartbeat,
    # not the last byte. Redis presence freshness (agent_registry's TTL key)
    # already tracks the same thing independently, via
    # agent_link._handle_heartbeat -> refresh_presence_heartbeat; this is
    # the WS-connection-teardown mirror of that same rule.
    last_heartbeat_at = utcnow()
    last_rekey_at = utcnow()
    last_ping_sent_at = utcnow()
    inbound_session = agent_link.LinkSessionState()
    # Held across loop iterations (only ever replaced once it actually
    # completes, in the receive-handling branch below) rather than recreated
    # every pass — recreating it each iteration would mean cancelling a
    # pending receive_bytes() every time a control frame wins the race below,
    # which risks dropping whatever the agent sends in that same window.
    receive_task: asyncio.Task[bytes] | None = None
    try:
        while True:
            # Server->agent cipher rekey, on this side's own clock and
            # independent of whatever the agent is doing with its own
            # outbound cipher. Checked once per loop iteration, so the
            # deadline is honoured within _LINK_POLL_SECONDS whether or not
            # the agent is sending anything.
            if (utcnow() - last_rekey_at).total_seconds() >= agent_crypto.REKEY_INTERVAL_SECONDS:
                try:
                    await _send_transport_rekey(websocket, responder, outbound_seq.next())
                except (WebSocketDisconnect, RuntimeError):
                    # The agent can drop between the frame we just handled and
                    # this send; that's an ordinary disconnect, not an error.
                    # (Starlette surfaces a send on an already-closed socket as
                    # RuntimeError.) Leaving the loop runs the same cleanup as
                    # any other disconnect.
                    break
                last_rekey_at = utcnow()

            # WS-protocol-level ping, on its own cadence and independent of
            # the rekey timer above — an active nudge distinct from the
            # application `heartbeat` frame the agent sends unprompted. The
            # agent replies to a `ping` with an immediate heartbeat (see
            # apps/agent/internal/link/link.go's `case frame.TypePing`),
            # which is what actually advances last_heartbeat_at below.
            if (utcnow() - last_ping_sent_at).total_seconds() >= _LINK_PING_INTERVAL_SECONDS:
                try:
                    await _send_ping(websocket, responder, outbound_seq.next())
                except (WebSocketDisconnect, RuntimeError):
                    break
                last_ping_sent_at = utcnow()

            # Race one persistent inbound-WS read against the control-plane
            # queue (Task 9), bounded by the same _LINK_POLL_SECONDS cadence
            # the old single `wait_for(receive_bytes(), ...)` used — a claimed
            # control frame short-circuits that wait instead of waiting out
            # the rest of the poll interval, which is the "immediate" half of
            # this task; the DB-status/pending-update poll fallback below is
            # otherwise untouched and still runs on its original cadence.
            if receive_task is None:
                receive_task = asyncio.ensure_future(websocket.receive_bytes())
            control_get_task = asyncio.ensure_future(control_queue.get())
            done, _pending = await asyncio.wait(
                {receive_task, control_get_task},
                timeout=_LINK_POLL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if control_get_task in done:
                claimed = control_get_task.result()
                if claimed.get("type") == TYPE_CAPABILITIES_SET:
                    claimed = {
                        **claimed,
                        "payload": _wire_grants(claimed.get("payload") or {}, capability_schema),
                    }
                frame_bytes = _control_frame_bytes(responder, claimed, outbound_seq.next())
                if frame_bytes is not None:
                    try:
                        await websocket.send_bytes(frame_bytes)
                    except (WebSocketDisconnect, RuntimeError):
                        break
                    if claimed.get("type") == TYPE_DISCONNECT:
                        # The frame telling the agent to disconnect has gone
                        # out — nothing more to do on this connection. (No
                        # call site publishes this frame type yet — Task 10
                        # is what wires revoke/reject to it — but delivery is
                        # ready the moment one does.)
                        break
            else:
                control_get_task.cancel()

            if not done:
                # Neither inbound WS data nor a control frame arrived within
                # the poll interval — identical to the old TimeoutError
                # branch this replaces.
                if (utcnow() - last_heartbeat_at).total_seconds() >= _LINK_DEAD_SECONDS:
                    break
                with SessionLocal() as db:
                    fresh = agent_registry.get_agent(db, agent_id)
                    if fresh is None or fresh.status != "active":
                        break
                pending = await agent_update.pop_pending_update(agent_id)
                if pending is not None:
                    update_frame = {
                        "v": 1,
                        "type": TYPE_UPDATE,
                        "seq": outbound_seq.next(),
                        "ts": utcnow().isoformat(),
                        "payload": pending,
                    }
                    try:
                        await websocket.send_bytes(
                            responder.encrypt(json.dumps(update_frame).encode())
                        )
                    except (WebSocketDisconnect, RuntimeError):
                        break
                continue

            if receive_task not in done:
                # Only a control frame fired this cycle — loop straight back
                # around for more rather than waiting out the rest of the
                # poll interval; `receive_task` itself is left untouched and
                # picked back up next iteration.
                continue

            try:
                ct = receive_task.result()
            except WebSocketDisconnect:
                break
            finally:
                receive_task = None

            try:
                pt = responder.decrypt(ct)
            except Exception as exc:
                # Deliberately still not fatal to the connection — an
                # adversarial or momentarily-desynced peer must not be able
                # to kill the link over one bad frame — but this used to be
                # a completely silent drop (Task 31's E2E investigation
                # flagged it as "the single most under-instrumented point in
                # the entire path", capable of swallowing a real frame, e.g.
                # an uninstall notification, with zero trace). Logged, not
                # recorded as a protocol_violation AgentEvent: that audit
                # trail is for receive_frame's decoded-but-invalid
                # rejections, and an undecryptable frame never gets that far.
                _logger.warning(
                    "agent %s: dropped undecryptable inbound /link frame: %s", agent_id, exc
                )
                continue

            with SessionLocal() as db:
                fresh = agent_registry.get_agent(db, agent_id)
                if fresh is None or fresh.status != "active":
                    break
                agent_frame = agent_link.receive_frame(db, fresh, pt, inbound_session)
                if agent_frame is None:
                    continue
                if agent_frame.type == TYPE_HEARTBEAT:
                    # The one and only thing that refreshes the dead-connection
                    # deadline — see last_heartbeat_at's docstring above.
                    last_heartbeat_at = utcnow()
                    # Refreshed here with `connection_id`, not inside
                    # agent_link._handle_heartbeat (which only ever sees
                    # agent_registry's default, process-wide WORKER_ID) —
                    # see connection_id's own docstring above for why the
                    # registry entry has to be scoped per-connection, not
                    # per-worker-process.
                    await agent_registry.refresh_agent_connection(agent_id, worker_id=connection_id)
                if agent_frame.type == TYPE_TRANSPORT_REKEY:
                    # Applied here, inline, rather than through
                    # agent_link.dispatch_frame: the swap has to land before
                    # the next receive_bytes/decrypt, since every frame the
                    # agent sends after this one is sealed under the new key.
                    # Note this runs after receive_frame's sequence guard on
                    # purpose — a replayed announcement must not be able to
                    # push our receive cipher a generation ahead of the
                    # agent's send cipher.
                    try:
                        rekey = TransportRekeyPayload.model_validate(agent_frame.payload)
                        if rekey.direction != REKEY_DIRECTION_OUTBOUND:
                            raise RekeyError(f"unexpected direction {rekey.direction!r}")
                        responder.rekey_recv(rekey.generation)
                        # Diagnostic only, mirrors the outbound log line above
                        # and link.go's applyInboundRekey — no key material.
                        _logger.info(
                            "agent %s: applied inbound transport.rekey (generation %d)",
                            agent_id,
                            rekey.generation,
                        )
                    except (ValidationError, RekeyError) as exc:
                        # Fatal: once the agent has rotated its send cipher,
                        # not applying the matching receive rekey leaves the
                        # two permanently out of step and nothing further
                        # would decrypt. Drop the connection and let the
                        # agent's reconnect re-handshake instead.
                        _logger.warning("agent %s: bad transport.rekey: %s", agent_id, exc)
                        agent_registry.record_event(
                            db,
                            agent_id,
                            "protocol_violation",
                            detail={"reason": "invalid_transport_rekey", "error": str(exc)[:200]},
                        )
                        db.commit()
                        break
                    continue
                await agent_link.dispatch_frame(db, fresh, agent_frame)
    finally:
        control_task.cancel()
        if receive_task is not None:
            receive_task.cancel()
        for task in (control_task, receive_task):
            if task is None:
                continue
            try:
                await task
            except (asyncio.CancelledError, Exception):
                # Both are expected here: cancellation raises CancelledError
                # on the awaited task itself, and websocket.receive_bytes()
                # can also raise WebSocketDisconnect if the socket closed out
                # from under it in the same instant. Neither should block or
                # fail this connection's teardown.
                pass
        await agent_registry.deregister_agent_connection(agent_id, worker_id=connection_id)
        await agent_registry.mark_presence_disconnected(agent_id)
        await agent_registry.broadcast_presence(agent_id, "disconnected")
        with SessionLocal() as db:
            agent_registry.record_event(db, agent_id, "disconnected")
            db.commit()


def _extract_client_ip(websocket: WebSocket) -> str:
    """Extract real client IP, honouring X-Forwarded-For set by nginx."""
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if websocket.client:
        return websocket.client.host
    return "unknown"


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
        _logger.debug("Agent presence WS ping loop error: %s", exc)
        main_task.cancel()


async def _redis_agent_listener(websocket: WebSocket, stop_event: asyncio.Event) -> None:
    """Mirrors ws_discovery.py's _redis_discovery_listener — see that
    docstring for why Redis pub/sub is the primary cross-worker path."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        await stop_event.wait()
        return

    pubsub = r.pubsub()
    try:
        await pubsub.subscribe("cb:agents:events")
        while not stop_event.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                if websocket.application_state == WebSocketState.DISCONNECTED:
                    break
                try:
                    await websocket.send_text(msg["data"])
                except Exception:
                    break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        _logger.debug("Redis agent listener error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


@authenticated_router.websocket("/stream")
async def agent_presence_stream(websocket: WebSocket) -> None:
    """Token-as-first-message auth — see ws_monitors.py's monitor_stream and
    ws_discovery.py's discovery_stream for the identical protocol this
    duplicates. Router-level Depends(require_auth) is defense-in-depth only;
    a browser's native WebSocket constructor cannot set an Authorization
    header on the handshake, so a bearer-token (no-cookie) client can never
    satisfy it — this handler's own check is the real gate."""
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
        raw_token = token_from_websocket_scope(dict(websocket.scope))
        if not raw_token:
            try:
                raw_token = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_STREAM_AUTH_TIMEOUT_SECONDS
                )
            except TimeoutError:
                await websocket.send_text(json.dumps({"error": "auth_timeout"}))
                await websocket.close(code=1008)
                return
            except WebSocketDisconnect:
                return

        authenticated = False
        user_id: int | None = None

        with SessionLocal() as db:
            cfg = get_or_create_settings(db)
            if cfg.jwt_secret and not is_session_revoked(db, raw_token):
                uid = decode_token(raw_token, cfg.jwt_secret)
                if uid is not None:
                    u = db.get(User, uid)
                    if u and u.is_active:
                        if not (u.locked_until and u.locked_until > utcnow()):
                            if not (
                                u.role == "demo" and u.demo_expires and u.demo_expires <= utcnow()
                            ):
                                authenticated = True
                                user_id = uid

        if not authenticated:
            _logger.warning("Agent presence WS auth failed (ip=%s)", client_ip)
            await websocket.send_text(json.dumps({"error": "unauthorized"}))
            await websocket.close(code=1008)
            return

        from app.core.ws_manager import ws_manager

        accepted = await ws_manager.connect(websocket, user_id=user_id, client_ip=client_ip)
        if not accepted:
            await websocket.send_text(json.dumps({"error": "connection_limit_exceeded"}))
            await websocket.close(code=1008)
            return

        await websocket.send_text(json.dumps({"status": "connected"}))

        _current_task = asyncio.current_task()
        assert _current_task is not None
        ping_task = asyncio.create_task(_ping_loop(websocket, _current_task))
        stop_event = asyncio.Event()
        listener_task = asyncio.create_task(_redis_agent_listener(websocket, stop_event))

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
            stop_event.set()
            ping_task.cancel()
            listener_task.cancel()
            await ws_manager.disconnect(websocket)

    except Exception as exc:
        _logger.error("Agent presence WS unhandled error (ip=%s): %s", client_ip, exc)
        try:
            from app.core.ws_manager import ws_manager

            await ws_manager.disconnect(websocket)
            await websocket.close(code=1011)
        except Exception:
            pass
