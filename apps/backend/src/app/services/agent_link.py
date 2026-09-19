"""Frame decode -> validate -> capability check -> dispatch. No domain logic
lives here — telemetry lands in telemetry_service, probe results in the
monitoring engine's result path, discovery findings in agent_discovery
(slices 2-4). This module only transports and authenticates.

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
from app.db.models import Agent, AgentEvent
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


@dataclasses.dataclass(frozen=True)
class FrameReceipt:
    """What `receive_frame` made of one inbound wire frame.

    It exists because the delivery watermark (`data.ack`) has to distinguish
    three outcomes that the old `AgentFrame | None` return collapsed into two:

      - **accepted** — `frame` is set. The caller dispatches it and only then
        advances the watermark, because the ack must mean "durably persisted",
        and `dispatch_frame` is what commits.
      - **terminally rejected, sequence known** — `frame` is None and
        `terminal_seq` is set. An unsupported version, a duplicate or a
        decreasing sequence: this server will never accept that frame, no
        matter how many times the agent resends it. Acknowledging it is what
        lets the agent's spool head move past it instead of wedging behind it
        forever and resending it until its cap evicts everything queued
        behind.
      - **rejected, sequence unknowable** — both None. A body that did not
        parse, a blank type, a negative sequence: there is no trustworthy
        number to acknowledge, so the caller stops acknowledging anything on
        that connection. The agent then commits nothing more and re-sends
        everything on reconnect. Harsh, correct, and rare.

    `terminal_seq` is never set alongside `frame`: an accepted frame's
    sequence is `frame.seq`, and reading it from here would invite advancing
    the watermark before the handler had actually stored anything.
    """

    frame: AgentFrame | None = None
    terminal_seq: int | None = None

    @property
    def accepted(self) -> bool:
        """Whether a frame came back to dispatch."""
        return self.frame is not None


# Frame types requiring no grant are transport-level (hello/heartbeat/log/
# capability.violation/update.status) and are simply absent from this map.
CAPABILITY_FOR_TYPE: dict[str, str] = {
    TYPE_TELEMETRY_HOST: "host_telemetry",
    TYPE_PROBE_RESULT: "remote_probe",
    TYPE_DISCOVERY_FINDING: "local_discovery",
}

Handler = Callable[[Session, Agent, AgentFrame], Awaitable[None]]


async def _handle_heartbeat(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """Refresh presence, and record the agent's reported spool backlog.

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
    if "spool_evicted_frames" in payload.model_fields_set:
        # What the agent's spool permanently destroyed to stay under its cap.
        #
        # It rides the heartbeat rather than `capability.violation` or a
        # readiness row, and the reasoning is recorded here because it is the
        # kind of choice that gets re-argued: the heartbeat already carries
        # spool state and this server already gates that on key *presence*, so
        # neither side needs a new mechanism; it re-asserts every 20s, so a
        # heartbeat lost to a dropped connection self-heals rather than losing
        # the report; `capability.violation` has a closed vocabulary about
        # scope refusals that an eviction would corrupt; and readiness is
        # about a collector's ability to run, which is not what failed — the
        # collector ran, the buffer beneath it overflowed.
        agent_registry.record_spool_evictions(
            db,
            agent,
            payload.spool_evicted_frames,
            payload.spool_evicted_bytes,
            payload.spool_evicted_oldest_ts,
            payload.spool_evicted_newest_ts,
        )
    # The connection-ownership registry is *not* refreshed here.
    # Refreshing it via agent_registry.refresh_agent_connection(agent.id)
    # would only ever have access to agent_registry's default,
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

    Both paths end with the same agent revoked, so both owe the same the design
    cleanup: every run this agent still holds is cancelled and its
    assignments are kept as unavailable rather than deleted. A run left open by
    either path holds `uq_monitor_probe_runs_active` for its monitor until the
    reconciliation pass expires it.

    The same argument carriesthe discovery cleanup, which this handler used
    to skip: from the moment the status flips, `dispatch_frame`'s grant gate
    drops this agent's own terminal summary, so a dispatch left open here stays
    open until the reconciliation pass expires it — and unlike a revoked agent,
    an uninstalled one is not coming back to finish it.

    No audit row is written here on top of `revoke_agent`'s. `revoked` is in
    `agent_registry.CHAINED_EVENT_TYPES`, so `record_event` already lands a
    hash-chained `agent_revoked` entry carrying this reason for *both* paths.
    `post_revoke`'s extra `agent_revoke_authorized` row is specifically the
    record of an operator authorizing a revoke; writing one from here would
    make a search for operator authorizations return self-service uninstalls.

    Commits before publishing, for the same reason `_handle_key_rotate` does:
    the frame claims something about durable state, so that state has to be
    durable first. `dispatch_frame`'s trailing commit is then a no-op.

    One thing `post_revoke` does that this path deliberately does NOT: publish a
    `disconnect` control frame. That frame is routed by the connection registry
    (`agent_registry.publish_agent_control_frame` → `claim_agent_control_frames`),
    and the registry entry for this agent is owned by *this* connection — the
    one-shot notifier `cb-agent uninstall` opened, which registered itself over
    the daemon's entry when it connected (see `link_stream`'s `connection_id`).
    Publishing here would therefore land on the notifier's own socket and tear
    it down before the delivery acknowledgement the CLI now waits on could be
    sent, turning a successful uninstall back into an unconfirmed one. The
    daemon's still-live connection needs no such push: `link_stream` re-reads
    the agent row on every frame and leaves the loop the moment the status is no
    longer `active`.
    """
    agent_registry.revoke_agent(db, agent.id, actor_user_id=None, reason="uninstalled by agent")
    cancellation = monitor_service.cancel_agent_probe_runs(
        db, agent.id, reason=monitor_service.CANCEL_AGENT_REVOKED
    )
    # Has no `agent_revoked`; `agent_unavailable` is what a job whose
    # executor no longer exists failed for — the same reason and the same
    # constant `post_revoke` passes.
    discovery_cancellation = agent_discovery.cancel_agent_dispatches(
        db, agent.id, reason=agent_discovery.ERROR_AGENT_UNAVAILABLE
    )
    db.commit()
    await monitor_service.publish_probe_cancels(cancellation)
    await agent_discovery.publish_discovery_cancels(discovery_cancellation)
    # The Agents page folds this straight into the row's status, which is how an
    # operator watching the list sees an uninstall land without reloading.
    await agent_registry.broadcast_presence(agent.id, "revoked")


async def _handle_host_telemetry(db: Session, agent: Agent, frame: AgentFrame) -> None:
    try:
        await agent_telemetry.ingest_host_sample(db, agent, frame.payload, frame.ts)
    except agent_telemetry.InvalidHostTelemetry as exc:
        # The sample is now gone. Count it *outside* the throttle below: the
        # event row is rate-limited to one a minute on purpose, so the audit
        # trail undercounts, and an operator must still be able to see how
        # many samples this server actually threw away. `ingest_host_sample`
        # raises this for an agent whose status is not `active`, which is a
        # perfectly ordinary steady state — one an agent can sit in for days,
        # silently losing every sample it sends.
        agent_registry.record_refused_frame(agent, agent_registry.REFUSAL_INVALID_HOST_TELEMETRY)
        record, count = agent_telemetry.recordable_violation(agent.id)
        if record:
            agent_registry.record_event(
                db, agent.id, "protocol_violation", detail={"reason": str(exc), "repeated": count}
            )
            db.commit()


async def _handle_probe_result(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """The only inbound frame that can move monitor state.

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
        # Counted outside the throttle, for the reason `_handle_host_telemetry`
        # sets out: the event row is one a minute, the loss is not.
        agent_registry.record_refused_frame(agent, agent_registry.REFUSAL_INVALID_PROBE_RESULT)
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
    operator for review.

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
        # Before the `audited` early return, not after: that branch wrote its
        # own event but the finding was still refused and dropped, and the
        # counter measures frames destroyed, not rows written.
        agent_registry.record_refused_frame(agent, agent_registry.REFUSAL_INVALID_DISCOVERY_FINDING)
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
# same event type — the contract asks for one vocabulary — but they mean opposite
# things about who refused, and only the agent-reported one carries a scope
# reason, so the row has to say which it is.
_VIOLATION_REPORTED_BY_AGENT = "agent"


async def _handle_capability_violation(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """The agent reporting that *it* refused something we asked for.

    `probe.Runtime.emitCapabilityViolation` sends this when the scope evaluator
    on the agent disagrees with the one that built the assignment. Before the design
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
        # precisely the frame type the no-untrusted-contents rule is about.
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


# Maps an `update.status` frame's `phase` to the distinct
# `agent_events` type it records — queue-time (`update_queued`) is recorded
# separately by api/agents.py:post_update, since that transition is entirely
# server-side and has no frame to derive from.
_UPDATE_STATUS_EVENT: dict[str, str] = {
    "started": "update_started",
    "succeeded": "update_succeeded",
    "failed": "update_failed",
    "rolled_back": "update_rolled_back",
}

# The full per-version update lifecycle, as event types: an attempt opens
# with update_queued (post_update, detail key `target_version`) or
# update_started, and closes with exactly one terminal type.
_UPDATE_ATTEMPT_EVENT_TYPES = frozenset({"update_queued", "update_started"})
_UPDATE_LIFECYCLE_EVENT_TYPES = _UPDATE_ATTEMPT_EVENT_TYPES | frozenset(
    _UPDATE_STATUS_EVENT.values()
)

# How many recent lifecycle events _is_replayed_update_status scans, newest
# first, before deciding. A version's lifecycle interleaves with every other
# version's, so the scan bound has to cover a busy agent's recent history
# rather than one attempt's event count; 64 is far more lifecycle rows than
# any single update produces, and the query stays a single indexed page.
_UPDATE_REPLAY_SCAN_LIMIT = 64


def _is_replayed_update_status(db: Session, agent: Agent, event_type: str, version: str) -> bool:
    """Whether one terminal `update.status` for *version* is a replay of an
    outcome this agent already recorded — the case the agent's durable
    pending-outcome record produces (the contract of
    docs/design/2026-09-16-agent-deployment-connection-plan.md): the old
    process wrote the outcome, sent it live, and re-exec'd; the new process
    replays it after its first accepted hello.ack, and the live send may
    already have landed, so the second arrival must not duplicate the
    timeline.

    The rule is deterministic rather than heuristic: scanning this agent's
    lifecycle events for this version newest-first, the most recent one
    decides. The same terminal event again means replay; an attempt marker
    (update_queued/update_started) recorded after it means a genuinely new
    attempt is reporting — so a re-issued update to the same version that
    fails identically twice still gets both failures on the timeline. Events
    for other versions are skipped, and a version with no prior terminal
    event is never a replay.
    """
    recent = (
        db.query(AgentEvent)
        .filter(
            AgentEvent.agent_id == agent.id,
            AgentEvent.event_type.in_(_UPDATE_LIFECYCLE_EVENT_TYPES),
        )
        .order_by(AgentEvent.id.desc())
        .limit(_UPDATE_REPLAY_SCAN_LIMIT)
        .all()
    )
    for event in recent:
        detail = event.detail or {}
        # update_queued records the target under `target_version` (see
        # api/agents.py:post_update); the status frames' events under `version`.
        event_version = detail.get("version", detail.get("target_version"))
        if event_version != version:
            continue
        if event.event_type in _UPDATE_ATTEMPT_EVENT_TYPES:
            return False
        if event.event_type == event_type:
            return True
    return False


# Every update is delivered twice by design: `api/agents.py:post_update` queues
# it in Redis *and* publishes an immediate control frame, so the second arrival
# is routine rather than exceptional. An agent that is already applying that
# exact version refuses the duplicate, and agents up to and including 0.4.2
# report that refusal as `phase="failed"` — the only phase the wire had for it.
#
# Taking that at face value is a real defect: the clear below drops
# `pending_update_version`, so when the updated binary reconnects and reports
# the target version, `agent_registry.update_hello_metadata` matches nothing and
# records no `version_changed`. A successful update silently loses its audit
# event, and the fleet's version history has a hole exactly where an update
# worked.
#
# Newer agents suppress the status entirely (`link.ErrUpdateAlreadyRunning`), so
# this match exists for agents already in the field — self-hosters upgrade on
# their own schedule, and the server has to keep telling the truth about a fleet
# that has not. Matched on the message because that is what those agents send;
# the string is their wire contract and must not be "tidied".
_DUPLICATE_INSTRUCTION_REFUSAL = "update already in progress"


def _is_duplicate_instruction_refusal(payload: UpdateStatusPayload) -> bool:
    """Whether a `failed` report is really "I am already doing this"."""
    if payload.phase != "failed":
        return False
    return (payload.error or "").startswith(_DUPLICATE_INSTRUCTION_REFUSAL)


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

    # The state transition runs before the dedupe check, deliberately: a
    # replayed terminal failure must still clear pending_update_version if
    # the original report somehow did not — the clear is idempotent (None
    # stays None), so ordering it first can never regress, while ordering it
    # second would leave the recovery path hostage to the dedupe scan.
    is_terminal_failure = payload.phase in ("failed", "rolled_back")
    if is_terminal_failure and _is_duplicate_instruction_refusal(payload):
        # Not this attempt's resolution: the agent refused a *duplicate* of an
        # instruction it is already applying. Clearing the target here is what
        # made a successful update record no `version_changed` at all — see
        # the constant's comment.
        is_terminal_failure = False
    if is_terminal_failure and agent.pending_update_version == payload.version:
        # This attempt is never going to reconnect at the target version — a
        # failed download/verify/swap, or a confirmed rollback to the prior
        # binary — so version_changed must not fire for it later. Clearing
        # here (rather than leaving it for update_hello_metadata to notice a
        # mismatch) also lets a *subsequent*, unrelated update be queued
        # immediately without this stale target lingering.
        agent.pending_update_version = None

    # A terminal outcome can legitimately arrive twice — sent live by
    # the old process and replayed by the re-exec'd one. The second arrival
    # is ignored rather than recorded, so the timeline shows one outcome per
    # attempt and no duplicate alerts; "started" is never replayed (the
    # agent treats it as best-effort) and needs no dedupe. The ignored
    # replay is still logged — it is the one externally-visible signal that
    # the durable-outcome path fired at all.
    if payload.phase in ("succeeded", "failed", "rolled_back") and _is_replayed_update_status(
        db, agent, event_type, payload.version
    ):
        _logger.info(
            "agent %s: replayed update.status(%s, %s) — already recorded, ignoring duplicate",
            agent.id,
            payload.phase,
            payload.version,
        )
        return

    detail: dict[str, str] = {"version": payload.version}
    if payload.error:
        detail["error"] = payload.error[:200]
    agent_registry.record_event(db, agent.id, event_type, detail=detail)


async def _handle_key_rotate(db: Session, agent: Agent, frame: AgentFrame) -> None:
    """agent -> server `key.rotate`, kind="device". the design owns
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
    the design/9 control-frame path: the agent's own atomic device.key swap
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
    and the cost is not disk — it is that thousands of identical rows bury
    the audit trail an operator would need to read.

    The log line is inside the throttle for the same reason. A flood that fills
    the log is as unreadable as one that fills the table, and `repeated` carries
    the magnitude either way.
    """
    record, count = agent_telemetry.recordable_violation(agent.id, reason)
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

    Thin wrapper over `receive_frame_receipt` keeping the original
    frame-or-None shape, which is all most callers (and every unit test that
    predates the delivery watermark) need. `ws_agents.link_stream` calls the
    receipt form directly because it also has to know *why* a frame was
    rejected — see `FrameReceipt`.

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
    return receive_frame_receipt(db, agent, raw, session).frame


def receive_frame_receipt(
    db: Session,
    agent: Agent,
    raw: bytes,
    session: LinkSessionState | None = None,
) -> FrameReceipt:
    """`receive_frame`, but reporting *why* a frame was rejected — see `FrameReceipt`.

    Rejections (each recording a `protocol_violation` AgentEvent and leaving
    the connection open) fall into two groups, and the split is what the
    delivery watermark reads:

      - `unsupported_version`, `duplicate_sequence`, `decreasing_sequence` —
        the frame decoded, so its sequence number is known and trustworthy,
        and this server's refusal is final. The receipt carries that sequence
        so the caller can acknowledge it: an agent must be able to move past a
        frame that will never be accepted.
      - `malformed_frame` — a body that did not parse, a blank type, or a
        negative sequence. Nothing here is a number worth acknowledging: an
        unparseable body has no sequence at all, and a blank type or a
        negative sequence means the envelope's own structure is untrustworthy,
        which is not a basis for telling an agent to discard its only copy of
        an observation. The receipt is empty and the caller stops
        acknowledging on that connection.

    `session` is omitted by most direct unit tests, in which case a throwaway
    LinkSessionState is used — every call is then treated as the first frame
    of its own session, so sequence checks pass trivially.
    """
    if session is None:
        session = LinkSessionState()

    try:
        candidate = AgentFrame.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        _record_protocol_violation(
            db, agent, reason="malformed_frame", detail={"error": str(exc)[:200]}
        )
        return FrameReceipt()

    if candidate.v != FRAME_VERSION:
        _record_protocol_violation(
            db,
            agent,
            reason="unsupported_version",
            detail={"v": candidate.v, "frame_type": candidate.type},
        )
        return FrameReceipt(terminal_seq=candidate.seq if candidate.seq >= 0 else None)

    if not candidate.type.strip():
        _record_protocol_violation(
            db,
            agent,
            reason="malformed_frame",
            detail={"seq": candidate.seq, "frame_type": candidate.type},
        )
        return FrameReceipt()

    if candidate.seq < 0:
        _record_protocol_violation(
            db,
            agent,
            reason="malformed_frame",
            detail={"seq": candidate.seq, "frame_type": candidate.type},
        )
        return FrameReceipt()

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
        # Terminal, and safe to acknowledge: a duplicate is one the server has
        # already handled and a decreasing sequence is one it will never
        # accept on this connection. Either way the agent may stop resending
        # it. The watermark only ever moves forward, so a stale number here
        # cannot walk it backwards.
        return FrameReceipt(terminal_seq=candidate.seq)

    session.last_seq = candidate.seq
    return FrameReceipt(frame=candidate)


async def dispatch_frame(db: Session, agent: Agent, frame: AgentFrame) -> None:
    required = CAPABILITY_FOR_TYPE.get(frame.type)
    if required is not None and not agent_registry.grants_dict(db, agent.id).get(required, False):
        # This gate drops the frame entirely — a `telemetry.host` sample from
        # an agent whose `host_telemetry` grant is off is destroyed here, not
        # queued. Counting it alongside the audit row is what lets an operator
        # see the *volume* of what a withheld grant is discarding, rather than
        # only that it happened at least once.
        # Unconditional here: every key of CAPABILITY_FOR_TYPE is a data
        # frame carrying an observation, so reaching this branch always means
        # a measurement was destroyed.
        agent_registry.record_refused_frame(agent, agent_registry.REFUSAL_CAPABILITY_WITHHELD)
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
