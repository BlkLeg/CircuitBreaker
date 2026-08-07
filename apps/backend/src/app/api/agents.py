from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import agent_crypto
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role
from app.core.time import utcnow
from app.db.bucket import epoch_bucket
from app.db.models import (
    Agent,
    AgentCapabilityReadiness,
    AgentEvent,
    AgentHostSample,
    AgentHostSampleHourly,
    Hardware,
    User,
)
from app.db.session import get_db
from app.schemas.agent_frame import TYPE_CAPABILITIES_SET, TYPE_DISCONNECT, TYPE_UPDATE
from app.schemas.agents import (
    AgentEventRead,
    AgentPatch,
    AgentPresenceRead,
    AgentRead,
    AgentSummary,
    ApproveRequest,
    CapabilitiesUpdateRequest,
    CapabilityGrant,
    HardwareSummary,
    InstallCommandResponse,
    PairingLookupRequest,
    PairingLookupResponse,
    RevokeRequest,
    ServerKeyRotationStatus,
    UpdateRequest,
)
from app.services import agent_capabilities, agent_enrollment, agent_registry, agent_update

router = APIRouter(tags=["agents"])


def _sample_json(row: AgentHostSample) -> dict[str, Any]:
    return {
        "sample_id": row.sample_id,
        "collected_at": row.collected_at,
        "status": row.status,
        "summary": {
            "cpu_pct": row.cpu_pct,
            "mem_pct": row.mem_pct,
            "root_disk_pct": row.root_disk_pct,
            "net_rx_bps": row.net_rx_bps,
            "net_tx_bps": row.net_tx_bps,
            "max_temp_c": row.max_temp_c,
            "load_1": row.load_1,
            "uptime_s": row.uptime_s,
        },
        "payload": row.raw,
        "projected": row.projected_at is not None,
    }


# History aggregation tables. Bucket width is the SQL grouping grain; the cap is
# `range duration / bucket width` and is enforced as a SQL LIMIT, so a response
# can never exceed it no matter how fast the agent's cadence is or how much
# history retention has kept. Keep the two dicts in step.
_HISTORY_DURATIONS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_HISTORY_BUCKET_SECONDS = {"1h": 30, "6h": 60, "24h": 300, "7d": 1800, "30d": 3600}
_HISTORY_MAX_POINTS = {"1h": 120, "6h": 360, "24h": 288, "7d": 336, "30d": 720}
# Ranges long enough to outlive raw retention, which is what makes the hourly
# rollup merge necessary rather than decorative.
_HISTORY_HOURLY_RANGES = frozenset({"7d", "30d"})
_HISTORY_SUMMARY_FIELDS = (
    "cpu_pct",
    "mem_pct",
    "root_disk_pct",
    "net_rx_bps",
    "net_tx_bps",
    "max_temp_c",
    "load_1",
    "uptime_s",
)


def _as_float(value: Any) -> float | None:
    """`avg()` over a BigInteger column comes back as Decimal; the chart wants a
    plain JSON number, and a NULL average stays None so a gap renders as a gap."""
    return None if value is None else float(value)


def _to_read(db: Session, agent: Agent) -> AgentRead:
    data = AgentRead.model_validate(agent)
    data.capabilities = {
        name: CapabilityGrant.model_validate(grant)
        for name, grant in agent_registry.structured_grants_dict(db, agent.id).items()
    }
    proposed = agent_registry.propose_hardware_match(db, agent)
    data.proposed_hardware_id = proposed.id if proposed else None
    data.proposed_hardware_name = proposed.name if proposed else None
    data.duplicate_machine_id = agent_registry.has_duplicate_machine_id(db, agent)
    return data


@router.get("", response_model=list[AgentSummary])
def get_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    return agent_registry.list_agents(db)


@router.get("/pending", response_model=list[AgentSummary])
def get_pending_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    return agent_registry.list_agents(db, status="pending")


@router.get("/capability-defaults", response_model=dict[str, CapabilityGrant])
def get_capability_defaults(
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    """The server capability registry's approval defaults (Task 14 / D-14).

    The single source the approval modal and the agent-detail capability editor
    read their preset and config fallbacks from, so a frontend constant can
    never drift from what an approve with `capabilities` omitted actually
    grants — pinned by
    `test_capability_defaults_endpoint_matches_what_an_omitted_approve_grants`.

    Declared before "/{agent_id}" so "capability-defaults" isn't parsed as an
    agent id, same as "/pending", "/install-command" and "/presence".

    These are *approval-time* defaults only: they say nothing about what any
    already-approved agent is granted, which is exactly the grant rows written
    at its approval and nothing else.
    """
    return {
        name: CapabilityGrant(
            enabled=definition.default_enabled,
            config=agent_capabilities.default_config_for(name),
        )
        for name, definition in agent_capabilities.CAPABILITY_DEFINITIONS.items()
    }


@router.get("/install-command", response_model=InstallCommandResponse)
def get_install_command(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    from app.services import agent_install

    server_url = f"{request.url.scheme}://{request.url.netloc}"
    return agent_install.build_install_command(db, server_url)


def _rotation_status(state: agent_crypto.ServerKeyRotationState) -> ServerKeyRotationStatus:
    return ServerKeyRotationStatus(
        active=state.rotation_active,
        current_key_fingerprint=hashlib.sha256(state.current_pub).hexdigest()[:32],
        successor_key_fingerprint=(
            hashlib.sha256(state.successor_pub).hexdigest()[:32]
            if state.successor_pub is not None
            else None
        ),
        started_at=state.started_at,
        overlap_expires_at=state.overlap_expires_at,
    )


@router.get("/server-key/status", response_model=ServerKeyRotationStatus)
def get_server_key_rotation_status(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Task 28: current/successor server identity key fingerprints and
    overlap timing — never key material itself, same as `/install-command`
    above never embeds a private key."""
    return _rotation_status(agent_crypto.load_server_key_rotation_state(db))


@router.post("/server-key/rotate", response_model=ServerKeyRotationStatus, status_code=201)
async def post_server_key_rotate(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Task 28: start a server-key rotation (fresh successor keypair, 7-day
    overlap by default). Rejects with 409 while a prior rotation's overlap is
    still active — the server has exactly one rotation in flight at a time
    (see `agent_crypto.start_server_key_rotation`'s docstring).

    Once the rotation is durably started, immediately pushes the successor
    key to every currently-connected agent (`agent_registry.
    broadcast_server_key_rotate`) rather than waiting for each one's next
    hello.ack to happen to pick it up — see that function's docstring for why
    a live connection needs this pushed proactively, not only resent lazily.
    """
    state = agent_crypto.start_server_key_rotation(db)
    if state is None:
        raise HTTPException(
            status_code=409,
            detail="A server-key rotation is already active (overlap window in progress)",
        )
    await agent_registry.broadcast_server_key_rotate(db, state)
    return _rotation_status(state)


@router.get("/presence", response_model=list[AgentPresenceRead])
async def get_agents_presence(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
    ids: Annotated[list[int] | None, Query()] = None,
) -> Any:
    """Bulk online/offline + grants + linked-hardware summary, one request for
    the whole fleet (or an explicit `ids` list) — what `AgentsPage` (Task 14)
    needs to render its table without an N+1 per-agent call.

    Declared before "/{agent_id}" so "presence" isn't parsed as an agent id,
    same as "/pending" and "/install-command" above.

    `ids=[]` (present but empty) intentionally returns no rows, distinct from
    omitting `ids` entirely (whole fleet) — mirrors monitor.py's
    target_summary/list_target_summaries `target_ids` convention.
    """
    if ids is not None and not ids:
        return []

    stmt = select(Agent)
    if ids is not None:
        stmt = stmt.where(Agent.id.in_(ids))
    agents = list(db.execute(stmt).scalars())
    agent_ids = [agent.id for agent in agents]

    presence = await agent_registry.bulk_presence(agent_ids)
    grants = agent_registry.bulk_structured_grants_dict(db, agent_ids)

    hardware_ids = {agent.hardware_id for agent in agents if agent.hardware_id is not None}
    hardware_by_id: dict[int, Hardware] = {}
    if hardware_ids:
        hardware_by_id = {
            hw.id: hw
            for hw in db.execute(select(Hardware).where(Hardware.id.in_(hardware_ids))).scalars()
        }

    return [
        AgentPresenceRead(
            agent_id=agent.id,
            online=presence[agent.id]["online"],
            connected_since=presence[agent.id]["connected_since"],
            last_seen_at=agent.last_seen_at,
            capabilities={
                name: CapabilityGrant.model_validate(grant)
                for name, grant in grants[agent.id].items()
            },
            hardware=(
                HardwareSummary.model_validate(hardware_by_id[agent.hardware_id])
                if agent.hardware_id in hardware_by_id
                else None
            ),
        )
        for agent in agents
    ]


@router.get("/{agent_id}/telemetry")
def get_agent_telemetry(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    latest = db.execute(
        select(AgentHostSample)
        .where(AgentHostSample.agent_id == agent_id)
        .order_by(AgentHostSample.collected_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    readiness = (
        db.execute(
            select(AgentCapabilityReadiness)
            .where(AgentCapabilityReadiness.agent_id == agent_id)
            .order_by(AgentCapabilityReadiness.collector)
        )
        .scalars()
        .all()
    )
    grant = agent_registry.structured_grants_dict(db, agent_id).get(
        "host_telemetry", {"enabled": False, "config": {}}
    )
    return {
        "latest": _sample_json(latest) if latest else None,
        "readiness": [
            {
                "collector": r.collector,
                "state": r.state,
                "reason": r.reason,
                "remediation": r.remediation,
                "missing": r.missing,
                "updated_at": r.updated_at,
            }
            for r in readiness
        ],
        "capability": grant,
        # The agent's last-reported outbound-spool backlog (Task 16, D-12).
        # It rides this endpoint rather than one of its own because the Agent
        # Detail page already polls it every 30s, so the catch-up indicator is
        # live with no second poll. `None` means the agent has never reported
        # (a build predating HeartbeatPayload) and renders the same as a
        # drained spool: nothing.
        "spool": {
            "depth": agent.spool_depth,
            "bytes": agent.spool_bytes,
            "reported_at": agent.spool_reported_at,
        },
        "hardware_id": agent.hardware_id,
    }


@router.get("/{agent_id}/telemetry/history")
def get_agent_telemetry_history(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
    range_name: str = Query(default="1h", alias="range", pattern="^(1h|6h|24h|7d|30d)$"),
) -> Any:
    """Bucketed chart series for one agent, aggregated entirely in SQL.

    Averaging happens in the database over an epoch-aligned grid, so the
    endpoint never materializes raw samples (or the `raw` JSONB payload) and
    never has to thin an oversized series after the fact. Long ranges also read
    `agent_host_sample_hourly` for the span that raw retention has already
    deleted, so `7d` and `30d` stay whole across the retention boundary.
    """
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    start = utcnow() - _HISTORY_DURATIONS[range_name]
    width = _HISTORY_BUCKET_SECONDS[range_name]
    cap = _HISTORY_MAX_POINTS[range_name]

    bucket = epoch_bucket(AgentHostSample.collected_at, width).label("bucket")
    aggregate = (
        select(
            bucket,
            func.count().label("sample_count"),
            *(
                func.avg(getattr(AgentHostSample, field)).label(field)
                for field in _HISTORY_SUMMARY_FIELDS
            ),
        )
        .where(
            AgentHostSample.agent_id == agent_id,
            AgentHostSample.collected_at >= start,
        )
        .group_by(bucket)
        .order_by(bucket.desc())
        .limit(cap)
    )
    points: list[dict[str, Any]] = [
        {
            "collected_at": row.bucket,
            "summary": {field: _as_float(getattr(row, field)) for field in _HISTORY_SUMMARY_FIELDS},
            "sample_count": row.sample_count,
        }
        # The LIMIT has to take the newest buckets, so the query sorts
        # descending and the response is flipped back to ascending here.
        for row in reversed(db.execute(aggregate).all())
    ]

    if range_name in _HISTORY_HOURLY_RANGES:
        # Scalar, not `min()` over materialized rows: this is only a boundary.
        raw_boundary = db.execute(
            select(func.min(AgentHostSample.collected_at)).where(
                AgentHostSample.agent_id == agent_id,
                AgentHostSample.collected_at >= start,
            )
        ).scalar()
        hourly = (
            db.execute(
                select(AgentHostSampleHourly)
                .where(
                    AgentHostSampleHourly.agent_id == agent_id,
                    AgentHostSampleHourly.bucket_at >= start,
                    AgentHostSampleHourly.bucket_at
                    < (raw_boundary if raw_boundary is not None else utcnow()),
                )
                .order_by(AgentHostSampleHourly.bucket_at)
                .limit(cap)
            )
            .scalars()
            .all()
        )
        # Hourly points are coarser than the 7d raw grain; they are emitted with
        # their true sample_count and left for the chart to interpolate rather
        # than being split into fabricated sub-hour points. `.get` normalizes to
        # the same eight keys for rollup rows written before `uptime_s` joined
        # the summary.
        points.extend(
            {
                "collected_at": row.bucket_at,
                "summary": {field: row.summary.get(field) for field in _HISTORY_SUMMARY_FIELDS},
                "sample_count": row.sample_count,
            }
            for row in hourly
        )
        points.sort(key=lambda point: point["collected_at"])
        points = points[-cap:]

    return {"range": range_name, "points": points}


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent_detail(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _to_read(db, agent)


@router.get("/{agent_id}/events", response_model=list[AgentEventRead])
def get_agent_events(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return list(
        db.execute(
            select(AgentEvent)
            .where(AgentEvent.agent_id == agent_id)
            .order_by(AgentEvent.created_at.desc())
        ).scalars()
    )


@router.patch("/{agent_id}", response_model=AgentRead)
def patch_agent(
    agent_id: int,
    payload: AgentPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("editor")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    fields = payload.model_dump(exclude_unset=True)
    # hardware_id (Task 19: host-link editing after approval) is handled
    # separately from a plain setattr, same as approve_agent's own
    # hardware_id param — it needs FK validation (a plain setattr would
    # otherwise surface an unhandled IntegrityError for a bogus id) and an
    # `agent_events` row recording the change, neither of which a bare field
    # assignment gives us. `name`/`notes` have neither concern, so they stay
    # on the generic path below.
    if "hardware_id" in fields:
        hardware_id = fields.pop("hardware_id")
        if hardware_id is not None and db.get(Hardware, hardware_id) is None:
            raise HTTPException(status_code=404, detail="Hardware not found")
        agent_registry.set_hardware_link(db, agent_id, hardware_id, actor_user_id=user.id)

    for field, value in fields.items():
        setattr(agent, field, value)
    db.commit()
    return _to_read(db, agent)


@router.post("/pairing/lookup", response_model=PairingLookupResponse)
@limiter.limit(lambda: get_limit("auth"))
async def post_pairing_lookup(
    request: Request,
    response: Response,
    payload: PairingLookupRequest,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    ip = get_remote_address(request)
    if await agent_enrollment.is_pairing_locked_out(ip):
        raise HTTPException(status_code=429, detail="Too many incorrect pairing codes")

    # consume, not resolve — the code has done its job once it identifies the
    # pending agent; single-use per spec §2.4.
    agent_id = await agent_enrollment.consume_pairing_code(payload.code)
    if agent_id is None:
        await agent_enrollment.record_pairing_miss(ip)
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown or expired pairing code")

    proposed = agent_registry.propose_hardware_match(db, agent)
    duplicate = agent_registry.has_duplicate_machine_id(db, agent)

    return PairingLookupResponse(
        agent_id=agent.id,
        hostname=agent.hostname,
        os=agent.os,
        arch=agent.arch,
        fingerprint=agent.fingerprint,
        proposed_hardware_id=proposed.id if proposed else None,
        proposed_hardware_name=proposed.name if proposed else None,
        duplicate_machine_id=duplicate,
    )


@router.post("/{agent_id}/approve", response_model=AgentRead)
async def post_approve(
    agent_id: int,
    payload: ApproveRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agent_registry.approve_agent(
        db,
        agent_id,
        approving_user_id=user.id,
        hardware_id=payload.hardware_id,
        host_link_action=payload.host_link_action,
        capability_overrides=payload.capabilities,
    )
    db.commit()
    await agent_registry.broadcast_presence(agent_id, "approved")
    return _to_read(db, agent)


@router.post("/{agent_id}/reject", response_model=AgentRead)
async def post_reject(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agent_registry.reject_agent(db, agent_id, actor_user_id=user.id)
    db.commit()
    await agent_registry.broadcast_presence(agent_id, "rejected")
    # Immediate cross-worker disconnect (Task 9's delivery path, Task 10's
    # trigger): a rejected agent is never expected to hold a live /link
    # socket in practice (enroll_stream only ever leaves a device pending or
    # active), but publishing here is harmless and cheap on the off chance
    # one is connected — same never-raises guarantee as
    # put_capabilities' publish above, so a dead/degraded Redis can't fail
    # this request. The DB status flip above is still authoritative recovery
    # if pub/sub delivery is missed entirely.
    await agent_registry.publish_agent_control_frame(
        agent_id, {"type": TYPE_DISCONNECT, "payload": {"reason": "rejected"}}
    )
    return _to_read(db, agent)


@router.post("/{agent_id}/revoke", response_model=AgentRead)
async def post_revoke(
    agent_id: int,
    payload: RevokeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agent_registry.revoke_agent(db, agent_id, actor_user_id=user.id, reason=payload.reason)
    db.commit()
    await agent_registry.broadcast_presence(agent_id, "revoked")
    # Immediate cross-worker disconnect (Task 9's delivery path, Task 10's
    # trigger): if the agent is connected right now, whichever worker holds
    # its /link socket picks this up via
    # agent_registry.claim_agent_control_frames and closes the connection
    # without waiting on the next poll interval. Never raises (see
    # publish_agent_control_frame's docstring) — a dead/degraded Redis must
    # not fail this request; the still-revoked DB status is the recovery
    # path an agent's own poll (or its next reconnect attempt) picks up.
    await agent_registry.publish_agent_control_frame(
        agent_id, {"type": TYPE_DISCONNECT, "payload": {"reason": payload.reason or "revoked"}}
    )
    return _to_read(db, agent)


@router.put("/{agent_id}/capabilities", response_model=AgentRead)
async def put_capabilities(
    agent_id: int,
    payload: CapabilitiesUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_registry.set_capability_grants(db, agent_id, payload.capabilities, actor_user_id=user.id)
    db.commit()
    # Immediate cross-worker push (Task 9) on top of the DB write above: if the
    # agent is connected right now, whichever worker holds its /link socket
    # picks this up via agent_registry.claim_agent_control_frames and applies
    # it without waiting on anything poll-based. The authoritative grants
    # dict is re-read post-commit (not `payload.capabilities`) so an agent
    # that was never granted some capability the request didn't mention still
    # gets the full, correct set — mirrors what the initial connect-time
    # capabilities.set send in ws_agents.py already does. Never raises (see
    # publish_agent_control_frame's docstring) — a dead/degraded Redis must
    # not fail this request; the agent still picks the change up next time it
    # (re)connects or via its own periodic status poll.
    await agent_registry.publish_agent_control_frame(
        agent_id,
        {
            "type": TYPE_CAPABILITIES_SET,
            "payload": agent_registry.structured_grants_dict(db, agent_id),
        },
    )
    return _to_read(db, agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> None:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.delete(agent)
    db.commit()


@router.post("/{agent_id}/update")
async def post_update(
    agent_id: int,
    payload: UpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Auto-select (when the caller doesn't pin a specific version) considers
    # only the globally-latest manifest version, by design: an explicit or
    # auto-selected version incompatible with this agent's OS/arch is still
    # rejected below via get_binary_sha256 returning None (404) — see
    # agent_update.latest_version's os_name/arch filter for an alternate,
    # "pick the newest *compatible* version instead" policy available to
    # other callers that want it.
    version = payload.version or agent_update.latest_version()
    if version is None:
        raise HTTPException(status_code=400, detail="No agent binaries available on this instance")

    sha256 = agent_update.get_binary_sha256(version, agent.os or "linux", agent.arch or "amd64")
    if sha256 is None:
        raise HTTPException(
            status_code=404,
            detail=f"No binary for {agent.os}/{agent.arch} at version {version}",
        )

    await agent_update.request_update(
        agent_id,
        version=version,
        sha256=sha256,
        arch=agent.arch or "amd64",
        os_name=agent.os or "linux",
    )
    # Immediate cross-worker push (Task 9), same reasoning as put_capabilities
    # above: request_update above already queues the pending update in Redis,
    # which link_stream's existing _LINK_POLL_SECONDS poll (agent_update.
    # pop_pending_update) picks up as the recovery fallback if this publish is
    # missed or Redis is briefly unavailable for it specifically — that
    # queued key is left untouched either way.
    await agent_registry.publish_agent_control_frame(
        agent_id,
        {
            "type": TYPE_UPDATE,
            "payload": {
                "version": version,
                "sha256": sha256,
                "arch": agent.arch or "amd64",
                "os": agent.os or "linux",
            },
        },
    )
    # Task 24: `update_queued` marks queue-time only — the fleet-visible
    # `version_changed` event doesn't fire until the new binary actually
    # reconnects and its hello reports this exact version (see
    # agent_registry.update_hello_metadata). `pending_update_version` is what
    # that later check compares against, and is also how a subsequent
    # `update.status` frame (started/succeeded/failed/rolled_back — Task 24,
    # agent_link._handle_update_status) knows which in-flight attempt it's
    # reporting on.
    agent.pending_update_version = version
    agent_registry.record_event(
        db,
        agent_id,
        "update_queued",
        actor_user_id=user.id,
        detail={"target_version": version},
    )
    db.commit()
    return {"status": "queued", "version": version}


# Unauthenticated — the agent has no user session; integrity comes from the
# SHA-256 delivered over the Noise-encrypted link, not from route auth.
binary_router = APIRouter(tags=["agents-binary"])


@binary_router.get("/binary/{version}/{os_name}/{arch}")
def get_binary(version: str, os_name: str, arch: str) -> FileResponse:
    try:
        path = agent_update.binary_path(version, os_name, arch)
    except ValueError:
        raise HTTPException(status_code=404, detail="Binary not found") from None
    if not path.exists():
        raise HTTPException(status_code=404, detail="Binary not found")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)
