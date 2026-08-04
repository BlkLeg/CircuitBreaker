"""Agent CRUD, presence, capability grants, and host linkage.

This module owns all mutation of `agents` / `agent_capability_grants` /
`agent_events`. No collector domain logic lives here — see
specs/2026-07-26-cb-agent-design.md §1.2 on agent_link.py's boundary, which
this module sits directly behind.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
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


def create_pending_agent(db: Session, **fields: Any) -> Agent:
    agent = Agent(status="pending", **fields)
    db.add(agent)
    db.flush()
    record_event(db, agent.id, "enrolled")
    return agent


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

    Only overwrites a field when the hello actually supplied a value for it —
    an old-shaped or partial hello payload (every `HelloPayload` field is
    optional) must never blank out data recorded at enrollment or on a prior
    hello. Caller is responsible for the commit/flush.
    """
    if payload.os is not None:
        agent.os = payload.os
    if payload.os_version is not None:
        agent.os_version = payload.os_version
    if payload.arch is not None:
        agent.arch = payload.arch
    if payload.agent_version is not None:
        agent.agent_version = payload.agent_version
    if payload.primary_macs:
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


def propose_hardware_match(db: Session, agent: Agent) -> Hardware | None:
    """Descending-confidence match: MAC -> hostname (spec §3.3).

    The design doc's match order is machine_id_hash -> MAC -> hostname, but
    `Hardware` has no `machine_id_hash` column in the current schema (only
    `Agent` does) — confirmed via `grep -n machine_id_hash
    apps/backend/src/app/db/models.py`. The machine_id_hash branch is
    dropped for slice 1 per the task brief's guidance; adding a matching
    column to `Hardware` is a reasonable follow-up migration but is not
    spec'd here and is not invented in this task.
    """
    for mac in agent.primary_macs or []:
        match = db.execute(select(Hardware).where(Hardware.mac_address == mac)).scalar_one_or_none()
        if match is not None:
            return match

    if agent.hostname:
        return db.execute(
            select(Hardware).where(Hardware.name == agent.hostname)
        ).scalar_one_or_none()

    return None


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
