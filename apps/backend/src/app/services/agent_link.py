"""Frame decode -> validate -> capability check -> dispatch. No domain logic
lives here — telemetry lands in telemetry_service, probe results in the
monitoring engine's result path, discovery findings in agent_discovery
(slices 2-4). This module only transports and authenticates (spec §1.2).

`receive_frame` is the validate stage: it decodes one inbound wire frame for
a /link session and rejects malformed bodies, unsupported protocol
versions, and non-increasing sequence numbers (replay/duplicate/decreasing)
before a frame ever reaches `dispatch_frame`'s capability check. Rejections
are recorded as a `protocol_violation` AgentEvent, reusing the same
`agent_registry.record_event` audit trail `dispatch_frame` already uses for
`capability_violation` below."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.log_sanitize import safe_log_fragment
from app.db.models import Agent
from app.schemas.agent_frame import (
    FRAME_VERSION,
    MAX_VIOLATION_ADDRESS_CHARS,
    MAX_VIOLATION_DETAIL_CHARS,
    MAX_VIOLATION_FRAME_TYPE_CHARS,
    TYPE_CAPABILITY_READINESS,
    TYPE_CAPABILITY_VIOLATION,
    TYPE_DISCOVERY_FINDING,
    TYPE_HEARTBEAT,
    TYPE_KEY_ROTATE,
    TYPE_LOG,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    TYPE_UNINSTALL,
    TYPE_UPDATE_STATUS,
    AgentFrame,
    CapabilityViolationPayload,
    HeartbeatPayload,
    KeyRotatePayload,
    UpdateStatusPayload,
)
from app.services import (
    agent_discovery,
    agent_probe,
    agent_registry,
    agent_telemetry,
    monitor_service,
)

_logger = logging.getLogger(__name__)


@dataclasses.dataclass
class LinkSessionState:
    """Per-connection inbound-sequence-tracking state for one /link session.

    ws_agents.py's link_stream creates exactly one of these per WebSocket
    connection (so a reconnect always starts a fresh sequence count, mirroring
    the agent's own per-session `seq` counter in internal/link/link.go), and
    threads it through every `receive_frame` call for that connection's
    lifetime. Callers that don't care about replay protection (most unit
    tests calling `dispatch_frame` directly) can simply omit it.
    """

    last_seq: int | None = None


# Frame types requiring no grant are transport-level (hello/heartbeat/log/
# capability.violation/update.status) and are simply absent from this map.
CAPABILITY_FOR_TYPE: dict[str, str] = {
    TYPE_TELEMETRY_HOST: "host_telemetry",
    TYPE_PROBE_RESULT: "remote_probe",
    TYPE_DISCOVERY_FINDING: "local_discovery",
}

Handler = Callable[[Session, Agent, AgentFrame], Awaitable[None]]


async def _handle_heartbeat(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """Refresh presence, and record the agent's reported spool backlog (D-12).

    The spool numbers ride the heartbeat rather than a frame type of their
    own because the backlog exists precisely *while* the link is up and
    draining: a hello-only value would pin a stale depth on screen for the
    whole catch-up window on a connection that may not reconnect for days.

    Persistence is gated on `"spool_depth" in payload.model_fields_set` —
    presence, not truthiness. The Go heartbeat carries no `omitempty`, so a
    current agent always sends both keys (explicit zeros once its backlog
    clears, which is the write that clears the UI indicator) while an agent
    that predates the field sends `{}` and must leave the columns NULL. See
    `agent_registry.record_spool_stats`.

    A malformed payload is logged and dropped rather than raised: it must not
    tear the link down or block presence, matching `ws_agents.py`'s posture
    for a malformed hello. `dispatch_frame` owns the commit.
    """
    import socket

    await agent_registry.refresh_presence_heartbeat(db, agent.id, worker=socket.gethostname())

    try:
        payload = HeartbeatPayload.model_validate(frame.payload)
    except ValidationError:
        _logger.debug("agent %s: malformed heartbeat payload: %r", agent.id, frame.payload)
        return
    if "spool_depth" in payload.model_fields_set:
        # `spool_bytes` is gated on presence too, not just `spool_depth`.
        # `record_spool_stats` reads `None` as "unknown, leave the column
        # alone" — passing `payload.spool_bytes` unconditionally would write a
        # fabricated 0 for a payload that carried only the depth. Unreachable
        # from a current agent (HeartbeatPayload has no omitempty, so both keys
        # always ship) but the semantics have to hold regardless of sender.
        size_bytes = payload.spool_bytes if "spool_bytes" in payload.model_fields_set else None
        agent_registry.record_spool_stats(agent, payload.spool_depth, size_bytes)
    # The connection-ownership registry (Task 8) is *not* refreshed here.
    # It used to be, via agent_registry.refresh_agent_connection(agent.id)
    # — but that call only ever has access to agent_registry's default,
    # process-wide WORKER_ID, whereas the registry entry itself must be
    # scoped per-connection (see ws_agents.py link_stream's `connection_id`
    # docstring for why: a second /link connection sharing one worker
    # process, e.g. cb-agent uninstall's one-shot notifier alongside an
    # agent's still-live daemon connection, would otherwise be
    # indistinguishable from it). link_stream refreshes it directly, in its
    # own TYPE_HEARTBEAT branch, where the connection's actual per-socket
    # id is in scope.


async def _handle_log(db: Session, agent: Agent, frame: AgentFrame) -> None:
    _logger.info("agent %s: %s", agent.id, frame.payload)


async def _handle_uninstall(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """Agent-initiated revoke. Must not diverge from `api/agents.py::post_revoke`.

    Both paths end with the same agent revoked, so both owe the same Slice 3
    cleanup (§8): every run this agent still holds is cancelled and its
    assignments are kept as unavailable rather than deleted. A run left open by
    either path holds `uq_monitor_probe_runs_active` for its monitor until the
    reconciliation pass expires it.

    Commits before publishing, for the same reason `_handle_key_rotate` does:
    the frame claims something about durable state, so that state has to be
    durable first. `dispatch_frame`'s trailing commit is then a no-op.
    """
    agent_registry.revoke_agent(db, agent.id, actor_user_id=None, reason="uninstalled by agent")
    cancellation = monitor_service.cancel_agent_probe_runs(
        db, agent.id, reason=monitor_service.CANCEL_AGENT_REVOKED
    )
    db.commit()
    await monitor_service.publish_probe_cancels(cancellation)


async def _handle_host_telemetry(db: Session, agent: Agent, frame: AgentFrame) -> None:
    try:
        await agent_telemetry.ingest_host_sample(db, agent, frame.payload, frame.ts)
    except agent_telemetry.InvalidHostTelemetry as exc:
        record, count = agent_telemetry.recordable_violation(agent.id)
        if record:
            agent_registry.record_event(
                db, agent.id, "protocol_violation", detail={"reason": str(exc), "repeated": count}
            )
            db.commit()


async def _handle_probe_result(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """The only inbound frame that can move monitor state (§4).

    `frame.ts` is deliberately not passed through: `probe.result` is a data
    frame and therefore spools, and a spooled frame keeps its original producer
    `TS` — so it is agent-clock provenance, never arrival time. The deadline
    rule is judged against the server's own clock inside
    `agent_probe.ingest_probe_result`.

    Rejections follow `_handle_host_telemetry`'s shape exactly — catch the
    domain error, rate-limit through `recordable_violation`, record one event,
    commit — with one addition: the event *type* comes from the error, so a
    result posted against a run this agent does not own is audited as a
    `capability_violation` rather than as a malformed body.
    """
    try:
        await agent_probe.ingest_probe_result(db, agent, frame.payload)
    except agent_probe.InvalidProbeResult as exc:
        record, count = agent_telemetry.recordable_violation(agent.id)
        if record:
            agent_registry.record_event(
                db,
                agent.id,
                exc.event_type,
                detail={"reason": str(exc), "repeated": count},
            )
            db.commit()


async def _handle_discovery_finding(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """The only inbound frame that puts agent-authored rows in front of an
    operator for review (plan §4, §5).

    `frame.ts` is deliberately not passed through, for the reason
    `_handle_probe_result` documents at length: `discovery.finding` is a data
    frame and therefore spools, so a replayed frame keeps its original producer
    `TS` — agent-clock provenance, never arrival time. The dispatch-lease rule is
    judged against the server's own clock inside
    `agent_discovery.ingest_discovery_finding`.

    Rejections follow `_handle_probe_result`'s shape exactly — catch the domain
    error, rate-limit through `recordable_violation`, record one event, commit —
    with one addition. `InvalidDiscoveryFinding.audited` marks the single branch
    that already wrote its own event: the finding-ceiling breach, which has to
    commit that audit atomically with closing the job rather than hand it back
    here. Returning before the limiter, rather than after it, matters — a breach
    that already recorded itself must not consume the window and suppress the
    next genuine rejection.
    """
    try:
        await agent_discovery.ingest_discovery_finding(db, agent, frame.payload)
    except agent_discovery.InvalidDiscoveryFinding as exc:
        if exc.audited:
            return
        record, count = agent_telemetry.recordable_violation(agent.id)
        if record:
            agent_registry.record_event(
                db,
                agent.id,
                exc.event_type,
                detail={"reason": str(exc), "repeated": count},
            )
            db.commit()


# Distinguishes an agent's own refusal report from the `capability_violation`
# row `dispatch_frame` writes when *this server* drops a frame. Both are the
# same event type — plan §7 asks for one vocabulary — but they mean opposite
# things about who refused, and only the agent-reported one carries a scope
# reason, so the row has to say which it is.
_VIOLATION_REPORTED_BY_AGENT = "agent"


async def _handle_capability_violation(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """The agent reporting that *it* refused something we asked for (plan §7).

    `probe.Runtime.emitCapabilityViolation` sends this when the scope evaluator
    on the agent disagrees with the one that built the assignment. Before Task 17
    the frame was declared and silently dropped, so the one signal that a backend
    bug is dispatching out-of-scope work produced no row at all and read as a
    flaky monitor instead.

    Two properties are load-bearing and neither is inherited from anywhere else
    in this module, because `capability.violation` is deliberately absent from
    `CAPABILITY_FOR_TYPE`: `dispatch_frame`'s grant gate never runs for it, so an
    agent with every capability disabled can still reach this handler.

      1. The payload is validated against `CapabilityViolationPayload` — a closed
         `reason` vocabulary and bounded free text — and anything outside it is
         dropped with a log line and no write, mirroring
         `_handle_update_status`'s unknown-phase branch. The destination is
         `agent_events.detail`, an unbounded JSONB column with no retention job.
      2. `recordable_violation` runs *before* the write, not after, so an agent
         emitting these as fast as its link allows costs one row per minute.

    The detail is assembled from named payload fields only. That is what keeps a
    banner or an evidence value out of the audit trail structurally rather than by
    review: an unknown wire key is ignored by the model and so has nothing to be
    copied from. The one free-text field goes through `safe_log_fragment`, the
    same way every reason on the finding-ingest path does.
    """
    try:
        payload = CapabilityViolationPayload.model_validate(frame.payload)
    except ValidationError:
        # The payload is not echoed. It is attacker-authored text, and this is
        # precisely the frame type plan §7's no-untrusted-contents rule is about.
        _logger.warning(
            "agent %s: dropped an out-of-contract capability.violation payload", agent.id
        )
        return

    record, count = agent_telemetry.recordable_violation(agent.id)
    if not record:
        return

    detail: dict[str, object] = {
        "reason": payload.reason,
        "reported_by": _VIOLATION_REPORTED_BY_AGENT,
        "repeated": count,
    }
    if payload.frame_type:
        detail["frame_type"] = safe_log_fragment(payload.frame_type, MAX_VIOLATION_FRAME_TYPE_CHARS)
    if payload.address:
        detail["address"] = safe_log_fragment(payload.address, MAX_VIOLATION_ADDRESS_CHARS)
    if payload.detail:
        detail["detail"] = safe_log_fragment(payload.detail, MAX_VIOLATION_DETAIL_CHARS)

    _logger.warning("agent %s reported a capability violation: %s", agent.id, payload.reason)
    agent_registry.record_event(db, agent.id, "capability_violation", detail=detail)
    db.commit()


async def _handle_readiness(db: Session, agent: Agent, frame: AgentFrame) -> None:
    try:
        await agent_telemetry.ingest_readiness(db, agent, frame.payload)
    except agent_telemetry.InvalidHostTelemetry as exc:
        agent_registry.record_event(db, agent.id, "protocol_violation", detail={"reason": str(exc)})
        db.commit()


# Task 24: maps an `update.status` frame's `phase` to the distinct
# `agent_events` type it records — queue-time (`update_queued`) is recorded
# separately by api/agents.py:post_update, since that transition is entirely
# server-side and has no frame to derive from.
_UPDATE_STATUS_EVENT: dict[str, str] = {
    "started": "update_started",
    "succeeded": "update_succeeded",
    "failed": "update_failed",
    "rolled_back": "update_rolled_back",
}


async def _handle_update_status(db: Session, agent: Agent, frame: AgentFrame) -> None:
    try:
        payload = UpdateStatusPayload.model_validate(frame.payload)
    except ValidationError:
        # Tolerate malformed payloads the same way _handle_log/_handle_uninstall
        # implicitly do for their own shapes — a bad self-report must not take
        # the connection down or otherwise block dispatch of later frames.
        _logger.warning("agent %s: malformed update.status payload: %r", agent.id, frame.payload)
        return

    event_type = _UPDATE_STATUS_EVENT.get(payload.phase)
    if event_type is None:
        _logger.warning("agent %s: unknown update.status phase %r", agent.id, payload.phase)
        return

    detail: dict[str, str] = {"version": payload.version}
    if payload.error:
        detail["error"] = payload.error[:200]
    agent_registry.record_event(db, agent.id, event_type, detail=detail)

    is_terminal_failure = payload.phase in ("failed", "rolled_back")
    if is_terminal_failure and agent.pending_update_version == payload.version:
        # This attempt is never going to reconnect at the target version — a
        # failed download/verify/swap, or a confirmed rollback to the prior
        # binary — so version_changed must not fire for it later. Clearing
        # here (rather than leaving it for update_hello_metadata to notice a
        # mismatch) also lets a *subsequent*, unrelated update be queued
        # immediately without this stale target lingering.
        agent.pending_update_version = None


async def _handle_key_rotate(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """agent -> server `key.rotate`, kind="device" (Task 27). Task 28 owns
    this same frame *type*'s other direction and kind — server -> agent,
    kind="server" — for the server's own static-key rotation; an agent never
    sends that kind, and this handler ignores it if one somehow arrives.

    Reusing `key.rotate` bidirectionally like this is deliberate, not an
    accident of a shared payload shape: Noise IK's responder never validates
    the initiator's static key against a known set at the crypto layer (see
    `core/agent_crypto.py`'s module docstring), so nothing about *receiving*
    this frame needs a distinct wire message to be secure — the fact that it
    arrived at all (decrypted, sequence-checked by `receive_frame`, dispatched
    here) over an already-established `/link` session for this exact `agent`
    row is itself the authorization Global Constraints require ("the
    authenticated old Noise channel authorizes device-key rotation"). No
    signature scheme is layered on top, and `payload.successor_pk` — an
    X25519 DH public key — is never treated as anything else.

    On acceptance, commits the pending-key row before publishing the
    `key.rotate` acknowledgment (kind="device") back to the agent over the
    Task 8/9 control-frame path: the agent's own atomic device.key swap
    happens only once it has that ack in hand, so it must never be sent
    before the pending key it confirms is durably stored.
    """
    try:
        payload = KeyRotatePayload.model_validate(frame.payload)
    except ValidationError:
        _logger.warning("agent %s: malformed key.rotate payload: %r", agent.id, frame.payload)
        return

    if payload.kind != "device":
        _logger.warning(
            "agent %s: unexpected inbound key.rotate kind %r (server-kind rotation is "
            "server -> agent only)",
            agent.id,
            payload.kind,
        )
        return

    accepted = agent_registry.start_device_key_rotation(db, agent, payload.successor_pk)
    if not accepted:
        return

    # Durably stored before the ack claims as much — see docstring above.
    db.commit()
    fresh = agent_registry.get_agent(db, agent.id)
    if fresh is None or fresh.pending_device_pk_expiry is None:  # pragma: no cover - defensive
        return
    await agent_registry.publish_agent_control_frame(
        agent.id,
        {
            "type": TYPE_KEY_ROTATE,
            "payload": {
                "kind": "device",
                "successor_pk": payload.successor_pk,
                "expiry": fresh.pending_device_pk_expiry.isoformat(),
            },
        },
    )


_HANDLERS: dict[str, Handler] = {
    TYPE_HEARTBEAT: _handle_heartbeat,
    TYPE_LOG: _handle_log,
    TYPE_UNINSTALL: _handle_uninstall,
    TYPE_UPDATE_STATUS: _handle_update_status,
    TYPE_KEY_ROTATE: _handle_key_rotate,
    TYPE_TELEMETRY_HOST: _handle_host_telemetry,
    TYPE_CAPABILITY_READINESS: _handle_readiness,
    TYPE_PROBE_RESULT: _handle_probe_result,
    TYPE_DISCOVERY_FINDING: _handle_discovery_finding,
    TYPE_CAPABILITY_VIOLATION: _handle_capability_violation,
}


def _record_protocol_violation(db: Session, agent: Agent, *, reason: str, detail: dict) -> None:
    """Security-relevant-rejection record for one dropped inbound frame,
    reusing the same agent_events audit trail dispatch_frame's
    capability_violation uses below.

    Rate-limited through `recordable_violation`, exactly as the
    capability_violation path above is: the first violation in a window writes a
    row and every later one only advances `repeated`. An agent that sends
    malformed frames in a loop would otherwise commit once per frame (route
    F24), and the cost is not disk — it is that thousands of identical rows bury
    the audit trail an operator would need to read.

    The log line is inside the throttle for the same reason. A flood that fills
    the log is as unreadable as one that fills the table, and `repeated` carries
    the magnitude either way.
    """
    record, count = agent_telemetry.recordable_violation(agent.id)
    if not record:
        return
    _logger.warning("agent %s: protocol violation (%s): %s", agent.id, reason, detail)
    agent_registry.record_event(
        db,
        agent.id,
        "protocol_violation",
        detail={"reason": reason, "repeated": count, **detail},
    )
    db.commit()


def receive_frame(
    db: Session,
    agent: Agent,
    raw: bytes,
    session: LinkSessionState | None = None,
) -> AgentFrame | None:
    """Decode and validate one inbound wire frame for a /link session.

    Rejects (recording a `protocol_violation` AgentEvent and returning None
    for the caller to drop the frame and keep the connection open):
      - malformed bodies — bytes that don't parse as an AgentFrame at all,
        or decode with a blank/empty `type` (schema-legal for pydantic's
        `str`, but structurally incomplete — mirrors the Go agent's
        `seqguard.go` `f.Type == ""` check) or a negative `seq` (never
        producible by the Go agent's `uint64` counter, but not excluded by
        the wire schema either);
      - unsupported protocol versions — `v` != FRAME_VERSION;
      - non-increasing sequence numbers — `seq` <= the last one accepted in
        this session (covers both exact-duplicate replays and any
        decreasing sequence).

    `session` is omitted by most direct unit tests (e.g. dispatch_frame's
    existing table), in which case a throwaway LinkSessionState is used —
    every call is then treated as the first frame of its own session, so
    sequence checks pass trivially and behavior matches the pre-Task-3
    unvalidated path. ws_agents.py's link_stream passes one shared
    LinkSessionState per connection so validation is real across the
    connection's lifetime.
    """
    if session is None:
        session = LinkSessionState()

    try:
        candidate = AgentFrame.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        _record_protocol_violation(
            db, agent, reason="malformed_frame", detail={"error": str(exc)[:200]}
        )
        return None

    if candidate.v != FRAME_VERSION:
        _record_protocol_violation(
            db,
            agent,
            reason="unsupported_version",
            detail={"v": candidate.v, "frame_type": candidate.type},
        )
        return None

    if not candidate.type.strip():
        _record_protocol_violation(
            db,
            agent,
            reason="malformed_frame",
            detail={"seq": candidate.seq, "frame_type": candidate.type},
        )
        return None

    if candidate.seq < 0:
        _record_protocol_violation(
            db,
            agent,
            reason="malformed_frame",
            detail={"seq": candidate.seq, "frame_type": candidate.type},
        )
        return None

    if session.last_seq is not None and candidate.seq <= session.last_seq:
        reason = (
            "duplicate_sequence" if candidate.seq == session.last_seq else "decreasing_sequence"
        )
        _record_protocol_violation(
            db,
            agent,
            reason=reason,
            detail={
                "seq": candidate.seq,
                "last_seq": session.last_seq,
                "frame_type": candidate.type,
            },
        )
        return None

    session.last_seq = candidate.seq
    return candidate


async def dispatch_frame(db: Session, agent: Agent, frame: AgentFrame) -> None:
    required = CAPABILITY_FOR_TYPE.get(frame.type)
    if required is not None and not agent_registry.grants_dict(db, agent.id).get(required, False):
        agent_registry.record_event(
            db,
            agent.id,
            "capability_violation",
            detail={"frame_type": frame.type},
        )
        db.commit()
        return

    handler = _HANDLERS.get(frame.type)
    if handler is not None:
        await handler(db, agent, frame)
        db.commit()
