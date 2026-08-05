"""Agent CRUD, presence, capability grants, and host linkage.

This module owns all mutation of `agents` / `agent_capability_grants` /
`agent_events`. No collector domain logic lives here — see
specs/2026-07-26-cb-agent-design.md §1.2 on agent_link.py's boundary, which
this module sits directly behind.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Agent, AgentCapabilityGrant, AgentEvent, Hardware
from app.schemas.agent_frame import HelloPayload

_logger = logging.getLogger(__name__)

DEFAULT_CAPABILITY_GRANTS: dict[str, bool] = {
    "host_telemetry": True,
    "remote_probe": False,
    "local_discovery": False,
}

# Task 21: cap on agents simultaneously awaiting approval. An anonymous
# /enroll flood using a fresh device keypair per connection creates a new
# `Agent` row every time (device_pk is unique, so there's no per-device
# reuse to fall back on), so without a ceiling nothing bounds how many
# pending rows — and their live-held /enroll poll connections — accumulate.
MAX_CONCURRENT_PENDING_AGENTS = 100


def create_pending_agent(db: Session, **fields: Any) -> Agent:
    agent = Agent(status="pending", **fields)
    db.add(agent)
    db.flush()
    record_event(db, agent.id, "enrolled")
    return agent


def count_pending_agents(db: Session) -> int:
    """Number of agents currently in `pending` status, i.e. awaiting
    approval. Backs the concurrent-pending-enrollment cap in
    ws_agents.enroll_stream."""
    return db.execute(
        select(func.count()).select_from(Agent).where(Agent.status == "pending")
    ).scalar_one()


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.get(Agent, agent_id)


def get_agent_by_device_pk(db: Session, device_pk: str) -> Agent | None:
    return db.execute(select(Agent).where(Agent.device_pk == device_pk)).scalar_one_or_none()


def update_hello_metadata(db: Session, agent: Agent, payload: HelloPayload) -> None:
    """Refresh the `Agent` row's device-reported fields from an accepted `hello`.

    Enrollment (`ws_agents.enroll_stream`) only ever sets os/os_version/arch/
    agent_version/primary_macs once, at enrollment time. This is the
    counterpart called on every accepted `/link` hello afterwards, so the row
    tracks reality as a device is upgraded or its network config changes (see
    specs/2026-07-26-cb-agent-design.md §4.6: "the agent reports its version
    in `hello`; the UI shows which agents are behind").

    Only overwrites a field when the hello payload actually *included* it —
    gated on presence (`payload.model_fields_set`), not truthiness. An
    old-shaped or partial hello payload (every `HelloPayload` field is
    optional) omits fields it doesn't know about, and those must never blank
    out data recorded at enrollment or on a prior hello. Conversely, a hello
    that explicitly sends a falsy value — e.g. `"primary_macs": []` because
    the device now has zero up network interfaces — must persist that value;
    checking truthiness instead of presence would make that update
    unrepresentable, since an omitted key and an explicit `[]` both parse to
    the same default. Caller is responsible for the commit/flush.
    """
    fields_set = payload.model_fields_set
    if "os" in fields_set:
        agent.os = payload.os
    if "os_version" in fields_set:
        agent.os_version = payload.os_version
    if "arch" in fields_set:
        agent.arch = payload.arch
    if "agent_version" in fields_set:
        agent.agent_version = payload.agent_version
    if "primary_macs" in fields_set:
        agent.primary_macs = payload.primary_macs


def list_agents(db: Session, *, status: str | None = None) -> list[Agent]:
    stmt = select(Agent)
    if status is not None:
        stmt = stmt.where(Agent.status == status)
    return list(db.execute(stmt.order_by(Agent.created_at.desc())).scalars().all())


def approve_agent(
    db: Session,
    agent_id: int,
    *,
    approving_user_id: int,
    hardware_id: int | None = None,
    capability_overrides: dict[str, bool] | None = None,
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")

    agent.status = "active"
    agent.approved_at = utcnow()
    agent.approved_by_user_id = approving_user_id
    if hardware_id is not None:
        agent.hardware_id = hardware_id

    grants = dict(DEFAULT_CAPABILITY_GRANTS)
    grants.update(capability_overrides or {})
    for capability, enabled in grants.items():
        db.add(
            AgentCapabilityGrant(
                agent_id=agent.id,
                capability=capability,
                enabled=enabled,
                granted_by_user_id=approving_user_id,
            )
        )

    record_event(db, agent.id, "approved", actor_user_id=approving_user_id)
    db.flush()
    return agent


def reject_agent(db: Session, agent_id: int, *, actor_user_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")
    agent.status = "rejected"
    record_event(db, agent.id, "rejected", actor_user_id=actor_user_id)
    db.flush()
    return agent


def revoke_agent(
    db: Session, agent_id: int, *, actor_user_id: int | None, reason: str | None = None
) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")
    agent.status = "revoked"
    agent.revoked_at = utcnow()
    agent.revoked_by_user_id = actor_user_id
    agent.revoke_reason = reason
    record_event(db, agent.id, "revoked", actor_user_id=actor_user_id, detail={"reason": reason})
    db.flush()
    return agent


def set_capability_grants(
    db: Session, agent_id: int, grants: dict[str, bool], *, actor_user_id: int
) -> list[AgentCapabilityGrant]:
    existing = {
        g.capability: g
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }
    result = []
    for capability, enabled in grants.items():
        grant = existing.get(capability)
        if grant is None:
            grant = AgentCapabilityGrant(agent_id=agent_id, capability=capability)
            db.add(grant)
        grant.enabled = enabled
        grant.granted_by_user_id = actor_user_id
        grant.granted_at = utcnow()
        result.append(grant)
    record_event(db, agent_id, "capability_changed", actor_user_id=actor_user_id, detail=grants)
    db.flush()
    return result


def grants_dict(db: Session, agent_id: int) -> dict[str, bool]:
    """Capability name -> enabled, for one agent.

    Consolidated here (rather than duplicated as a private helper in
    api/agents.py and services/agent_link.py, as the plan text originally
    had it) per a cross-task consistency ruling: this module is already the
    single place agent state mutates, so it's also the single place that
    reduces AgentCapabilityGrant rows to a lookup dict. Tasks 9 and 12 import
    this function instead of redefining it.
    """
    return {
        g.capability: g.enabled
        for g in db.execute(
            select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id == agent_id)
        ).scalars()
    }


def bulk_grants_dict(db: Session, agent_ids: list[int]) -> dict[int, dict[str, bool]]:
    """`grants_dict`, but for many agents in one query.

    The bulk presence endpoint (Task 12) needs per-agent capability grants for
    a whole fleet without issuing one `AgentCapabilityGrant` SELECT per agent.
    Every id in `agent_ids` is present in the result (mapped to `{}` if it has
    no grant rows) so callers can index it unconditionally rather than
    special-casing a missing key.
    """
    result: dict[int, dict[str, bool]] = {agent_id: {} for agent_id in agent_ids}
    if not agent_ids:
        return result
    for g in db.execute(
        select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_id.in_(agent_ids))
    ).scalars():
        result.setdefault(g.agent_id, {})[g.capability] = g.enabled
    return result


def propose_hardware_match(db: Session, agent: Agent) -> Hardware | None:
    """Descending-confidence match: machine_id_hash -> MAC -> hostname (spec §3.3).

    `Hardware.machine_id_hash` (Task 16) is the strongest signal — a device's
    `/etc/machine-id` hash survives hostname renames and NIC swaps that would
    defeat the MAC/hostname branches below, so it's checked first. Falls
    through to an exact MAC-address match (any of the agent's reported
    `primary_macs`), then an exact hostname match, returning the first hit at
    whichever confidence tier produces one; `None` if nothing matches at any
    tier.
    """
    if agent.machine_id_hash:
        match = db.execute(
            select(Hardware).where(Hardware.machine_id_hash == agent.machine_id_hash)
        ).scalar_one_or_none()
        if match is not None:
            return match

    for mac in agent.primary_macs or []:
        match = db.execute(select(Hardware).where(Hardware.mac_address == mac)).scalar_one_or_none()
        if match is not None:
            return match

    if agent.hostname:
        return db.execute(
            select(Hardware).where(Hardware.name == agent.hostname)
        ).scalar_one_or_none()

    return None


def has_duplicate_machine_id(db: Session, agent: Agent) -> bool:
    """True if some *other* `Agent` row reports the same `machine_id_hash`.

    Surfaced identically from both the agent-detail endpoint and the
    pairing-lookup endpoint (api/agents.py `_to_read` / `post_pairing_lookup`)
    so an operator sees the same duplicate-machine warning regardless of
    which screen (fleet detail view vs. pairing-code approval flow) they use
    to review a device — see spec §3.3's "Duplicate machine_id_hash" row.
    An agent with no reported machine_id_hash (old-shaped hello, or a host
    that couldn't read /etc/machine-id) can never be flagged as a duplicate;
    there is nothing to compare.
    """
    if not agent.machine_id_hash:
        return False
    return (
        db.execute(
            select(Agent).where(
                Agent.machine_id_hash == agent.machine_id_hash,
                Agent.id != agent.id,
            )
        ).scalar_one_or_none()
        is not None
    )


def record_event(
    db: Session,
    agent_id: int,
    event_type: str,
    *,
    actor_user_id: int | None = None,
    detail: dict | None = None,
) -> AgentEvent:
    event = AgentEvent(
        agent_id=agent_id, event_type=event_type, actor_user_id=actor_user_id, detail=detail
    )
    db.add(event)
    db.flush()
    return event


_PRESENCE_TTL_SECONDS = 60
_LAST_SEEN_WRITE_THROTTLE_SECONDS = 60


def _presence_key(agent_id: int) -> str:
    return f"agent:presence:{agent_id}"


async def mark_presence_connected(agent_id: int, worker: str) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    payload = json.dumps({"connected_at": utcnow().isoformat(), "worker": worker})
    await r.setex(_presence_key(agent_id), _PRESENCE_TTL_SECONDS, payload)


async def mark_presence_disconnected(agent_id: int) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    await r.delete(_presence_key(agent_id))


async def is_agent_online(agent_id: int) -> bool:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False
    return bool(await r.exists(_presence_key(agent_id)))


def _offline_presence() -> dict[str, Any]:
    return {"online": False, "connected_since": None}


async def bulk_presence(agent_ids: list[int]) -> dict[int, dict[str, Any]]:
    """`is_agent_online`, but for a whole fleet in one Redis round trip.

    The bulk presence REST endpoint (Task 12) must not do one `EXISTS`/`GET`
    per agent — this issues a single `MGET` across every agent's
    `agent:presence:{id}` key instead. Every id in `agent_ids` is present in
    the result, mapped to `{"online": bool, "connected_since": datetime |
    None}`: a missing or TTL-expired key (never connected, or the connection
    dropped without a fresh heartbeat) resolves to `online=False,
    connected_since=None`, exactly as a single `is_agent_online` call would
    for that agent — and a Redis-unavailable outcome degrades every agent to
    that same offline default, mirroring `is_agent_online`'s own
    degrade-gracefully contract rather than raising or partially answering.
    """
    if not agent_ids:
        return {}

    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return {agent_id: _offline_presence() for agent_id in agent_ids}

    keys = [_presence_key(agent_id) for agent_id in agent_ids]
    raw_values = await r.mget(keys)

    result: dict[int, dict[str, Any]] = {}
    for agent_id, raw in zip(agent_ids, raw_values, strict=True):
        if raw is None:
            result[agent_id] = _offline_presence()
            continue
        connected_since: datetime | None = None
        try:
            payload = json.loads(raw)
            connected_at = payload.get("connected_at")
            if connected_at:
                connected_since = datetime.fromisoformat(connected_at)
        except (TypeError, ValueError):
            _logger.warning("agent %s: malformed presence payload dropped", agent_id)
        result[agent_id] = {"online": True, "connected_since": connected_since}
    return result


async def refresh_presence_heartbeat(db: Session, agent_id: int, worker: str) -> None:
    """Refresh the Redis presence TTL every heartbeat; throttle the Postgres
    last_seen_at write to roughly once per minute so a large fleet doesn't
    generate one write per agent per 20s heartbeat."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is not None:
        payload = json.dumps({"connected_at": utcnow().isoformat(), "worker": worker})
        await r.setex(_presence_key(agent_id), _PRESENCE_TTL_SECONDS, payload)

    agent = db.get(Agent, agent_id)
    if agent is None:
        return
    now = utcnow()
    if (
        agent.last_seen_at is None
        or (now - agent.last_seen_at).total_seconds() >= _LAST_SEEN_WRITE_THROTTLE_SECONDS
    ):
        agent.last_seen_at = now
        db.flush()


_AGENTS_REDIS_CHANNEL = "cb:agents:events"


async def broadcast_presence(agent_id: int, event_type: str, detail: dict | None = None) -> None:
    """Push a presence event to every live WS /api/agents/stream viewer.

    Redis pub/sub is the cross-worker path (mirrors discovery_service.py's
    _emit_ws_event), but ws_manager.broadcast is always also attempted on
    this worker: /stream's Redis subscribe (Task 15) happens asynchronously
    right after connect, so a viewer whose subscribe hasn't landed yet would
    otherwise miss the event outright. Presence flips are infrequent enough
    that occasional duplicate delivery of an idempotent status message is a
    non-issue. Never raises — a bad payload or dead Redis/NATS must not
    abort the caller's own mutation (approve/reject/revoke, connect/
    disconnect).
    """
    from app.core import subjects
    from app.core.nats_client import nats_client
    from app.core.redis import get_redis
    from app.core.ws_manager import ws_manager

    message = {"agent_id": agent_id, "event_type": event_type, "detail": detail}

    try:
        r = await get_redis()
        if r is not None:
            await r.publish(_AGENTS_REDIS_CHANNEL, json.dumps(message, default=str))
    except Exception as exc:
        _logger.debug("agent presence broadcast (redis) failed: %s", exc)

    try:
        await ws_manager.broadcast(message)
    except Exception as exc:
        _logger.debug("agent presence broadcast (ws_manager) failed: %s", exc)

    try:
        await nats_client.publish(subjects.AGENT_EVENT, message)
    except Exception as exc:
        _logger.debug("agent presence broadcast (nats) failed: %s", exc)


WORKER_ID = uuid.uuid4().hex
"""Identifies *this* worker process for cross-worker /link connection
ownership and control-frame routing (Task 8).

No existing identifier in the codebase is fit for this purpose. The closest
candidate — the `worker` string `mark_presence_connected`/
`refresh_presence_heartbeat` already record (`socket.gethostname()`, set by
ws_agents.py's `link_stream`) — is a purely cosmetic display label for the UI
presence payload, not a routing key: multiple backend worker processes
commonly run on one host (e.g. multiple uvicorn/gunicorn workers), so
hostname alone cannot say *which one* currently holds a given agent's live
socket. There is likewise no existing per-process id from the NATS
integration (nats_client.py has no client-id concept surfaced to callers) or
from Redis channel naming (`cb:agents:events` is a single shared channel, not
per-worker). Absent such a concept, this is the "reasonable per-process UUID
generated at worker startup" the task brief allows for: generated once, at
this module's import time (i.e. once per worker process), and stable for
that process's lifetime.
"""

_CONNECTION_KEY_PREFIX = "agent:connection:"
# Same cadence as presence (_PRESENCE_TTL_SECONDS) — refreshed alongside it
# from the same heartbeat, so the two keys expire together rather than one
# outliving the other.
_CONNECTION_TTL_SECONDS = _PRESENCE_TTL_SECONDS


def _connection_key(agent_id: int) -> str:
    return f"{_CONNECTION_KEY_PREFIX}{agent_id}"


async def register_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> bool:
    """Record that `worker_id` currently holds `agent_id`'s live /link socket.

    Mirrors `mark_presence_connected`'s TTL-key pattern exactly (same 60s
    TTL). Unlike `mark_presence_connected`, a Redis-unavailable outcome is
    logged rather than silently swallowed: the /link WebSocket itself doesn't
    need Redis and can proceed either way, but with no registry entry this
    worker becomes unreachable for cross-worker control routing for as long
    as Redis stays down — a guarantee the global constraints call out as
    something that must "fail clearly, not silently weaken". Returns True on
    success, False when Redis is unavailable.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        _logger.warning(
            "agent %s: connection registry unavailable (Redis down) — "
            "cross-worker control routing disabled for this connection",
            agent_id,
        )
        return False
    await r.setex(_connection_key(agent_id), _CONNECTION_TTL_SECONDS, worker_id)
    return True


async def refresh_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> None:
    """Refresh the connection-registry TTL — call on the same cadence as
    `refresh_presence_heartbeat` (see agent_link.py's `_handle_heartbeat`),
    so a long-lived connection's registry entry never expires out from under
    it purely from the passage of time."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    await r.setex(_connection_key(agent_id), _CONNECTION_TTL_SECONDS, worker_id)


# Atomic compare-and-delete (executed server-side via EVALSHA, the same
# register_script/EVALSHA idiom rate_limit_middleware.py uses for its
# sliding-window check). A GET-then-DELETE from Python would be two separate
# round trips with a window between them for another worker's
# register_agent_connection (SETEX) to land — this worker's DELETE would then
# blindly remove the new owner's freshly-written entry. Running the
# compare-and-delete as a single Lua script closes that window: Redis
# executes it as one atomic server-side step, so no other command can
# interleave between the GET and the DELETE.
_COMPARE_AND_DELETE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def deregister_agent_connection(agent_id: int, *, worker_id: str = WORKER_ID) -> None:
    """Remove the registry entry, but only if it's still this worker's.

    A fast disconnect/reconnect can land the agent on a *different* worker
    before this worker's own teardown runs (its `finally` block races the new
    connection's own `register_agent_connection`). Blindly deleting on
    disconnect — as `mark_presence_disconnected` does for the presence key —
    would then erase the new owner's freshly-written entry. The compare and
    the delete run as a single atomic Lua script (`_COMPARE_AND_DELETE_LUA`)
    rather than a GET followed by a DELETE, so only ever the row this worker
    itself owns is removed, even if another worker's register races in
    between what would otherwise be two separate round trips.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    script = r.register_script(_COMPARE_AND_DELETE_LUA)
    await script(keys=[_connection_key(agent_id)], args=[worker_id])


async def get_agent_connection_owner(agent_id: int) -> str | None:
    """The `worker_id` of whichever worker currently holds `agent_id`'s live
    /link socket, or None if no worker is registered (agent offline, or the
    registry entry expired)."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    return cast(str | None, await cast(Awaitable[Any], r.get(_connection_key(agent_id))))


_CONTROL_CHANNEL_PREFIX = "cb:agents:control:"


def _control_channel(agent_id: int) -> str:
    return f"{_CONTROL_CHANNEL_PREFIX}{agent_id}"


async def publish_agent_control_frame(agent_id: int, frame: dict) -> bool:
    """Hand a control frame to whichever worker currently holds `agent_id`'s
    live /link socket.

    This is the generic delivery primitive only: it hands `frame` off over
    `agent_id`'s dedicated Redis pub/sub channel, published by any worker
    process regardless of whether it owns the connection. It does NOT itself
    know or care what `frame` means — Task 9 wires specific frame types
    (capabilities.set, update, disconnect, key-rotation, ping) through this.
    Actual delivery to the live socket depends on the owning worker running
    `claim_agent_control_frames` for this agent (also Task 9's concern).

    Never raises — a bad payload or dead Redis must not abort the caller's
    own control-plane action. Returns True once the frame has been published
    (note: publish success does not guarantee an owning worker was listening
    — Redis pub/sub has no persistence/replay for messages published to a
    channel with no current subscriber), False when Redis is unavailable or
    publish itself failed.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        _logger.warning("agent %s: control frame not published — Redis unavailable", agent_id)
        return False
    try:
        await r.publish(_control_channel(agent_id), json.dumps(frame, default=str))
        return True
    except Exception as exc:
        _logger.warning("agent %s: control frame publish failed: %s", agent_id, exc)
        return False


async def claim_agent_control_frames(
    agent_id: int, *, worker_id: str = WORKER_ID
) -> AsyncIterator[dict]:
    """Async generator: yields each control frame published for `agent_id`
    while — and only while — `worker_id` is currently registered as the
    owner of that agent's connection (`register_agent_connection`).

    This is the "claim" half of the delivery primitive: subscribing to
    `agent_id`'s channel alone is not sufficient authorization to act on a
    frame, because a message can arrive after this worker's own connection
    has already handed off to another worker (e.g. the agent reconnected
    elsewhere) but before whatever holds this generator has gotten around to
    stopping it. Re-checking ownership per message, rather than once at
    subscribe time, closes that window — a frame that arrives for an agent
    this worker no longer owns is silently dropped rather than delivered to
    a socket that's already gone.

    Callers own the generator's lifetime: run it inside its own `asyncio`
    task for the life of the /link connection and cancel that task to stop
    listening (e.g. when the socket closes) — cancellation reaches this
    generator as an ordinary `GeneratorExit`/`CancelledError` at its current
    `await`, and the `finally` block below unsubscribes cleanly, mirroring
    `_redis_agent_listener`'s teardown in ws_agents.py. Wiring this into
    `link_stream` itself is Task 9's job, not this primitive's.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(_control_channel(agent_id))
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None or msg.get("type") != "message":
                continue
            owner = await get_agent_connection_owner(agent_id)
            if owner != worker_id:
                continue
            try:
                yield json.loads(msg["data"])
            except (TypeError, ValueError) as exc:
                _logger.warning("agent %s: malformed control frame dropped: %s", agent_id, exc)
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.aclose()
        except Exception:
            pass


_PENDING_EXPIRY_DAYS = 7


def expire_stale_pending_agents(db: Session) -> int:
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=_PENDING_EXPIRY_DAYS)
    query = select(Agent).where(Agent.status == "pending", Agent.enrolled_at < cutoff)
    stale = list(db.execute(query).scalars())
    for agent in stale:
        agent.status = "rejected"
        record_event(db, agent.id, "rejected", detail={"reason": "pending_expired"})
    db.commit()
    return len(stale)
