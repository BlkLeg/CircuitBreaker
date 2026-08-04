"""Frame decode -> validate -> capability check -> dispatch. No domain logic
lives here — telemetry lands in telemetry_service, probe results in the
monitoring engine's result path, discovery findings in
discovery_import_service (slices 2-4). This module only transports and
authenticates (spec §1.2).

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

from app.db.models import Agent
from app.schemas.agent_frame import (
    FRAME_VERSION,
    TYPE_DISCOVERY_FINDING,
    TYPE_HEARTBEAT,
    TYPE_LOG,
    TYPE_PROBE_RESULT,
    TYPE_TELEMETRY_HOST,
    TYPE_UNINSTALL,
    AgentFrame,
)
from app.services import agent_registry

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
# capability.violation) and are simply absent from this map.
CAPABILITY_FOR_TYPE: dict[str, str] = {
    TYPE_TELEMETRY_HOST: "host_telemetry",
    TYPE_PROBE_RESULT: "remote_probe",
    TYPE_DISCOVERY_FINDING: "local_discovery",
}

Handler = Callable[[Session, Agent, AgentFrame], Awaitable[None]]


async def _handle_heartbeat(db: Session, agent: Agent, frame: AgentFrame) -> None:
    import socket

    await agent_registry.refresh_presence_heartbeat(db, agent.id, worker=socket.gethostname())
    # Same refresh cadence as presence above, for the connection-ownership
    # registry (Task 8) — keeps the two TTL keys expiring in lockstep rather
    # than one outliving the other.
    await agent_registry.refresh_agent_connection(agent.id)


async def _handle_log(db: Session, agent: Agent, frame: AgentFrame) -> None:
    _logger.info("agent %s: %s", agent.id, frame.payload)


async def _handle_uninstall(db: Session, agent: Agent, frame: AgentFrame) -> None:
    agent_registry.revoke_agent(db, agent.id, actor_user_id=None, reason="uninstalled by agent")


_HANDLERS: dict[str, Handler] = {
    TYPE_HEARTBEAT: _handle_heartbeat,
    TYPE_LOG: _handle_log,
    TYPE_UNINSTALL: _handle_uninstall,
}


def _record_protocol_violation(db: Session, agent: Agent, *, reason: str, detail: dict) -> None:
    """Security-relevant-rejection record for one dropped inbound frame,
    reusing the same agent_events audit trail dispatch_frame's
    capability_violation uses below."""
    _logger.warning("agent %s: protocol violation (%s): %s", agent.id, reason, detail)
    agent_registry.record_event(
        db, agent.id, "protocol_violation", detail={"reason": reason, **detail}
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
