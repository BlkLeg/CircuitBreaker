from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from slowapi.util import get_remote_address
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import agent_crypto, agent_scope
from app.core.audit import log_audit
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role, require_scope
from app.core.scheduler import reload_discovery_jobs
from app.core.time import utcnow
from app.db.bucket import epoch_bucket
from app.db.models import (
    Agent,
    AgentCapabilityReadiness,
    AgentEvent,
    AgentHostSample,
    AgentHostSampleHourly,
    DiscoveryProfile,
    Hardware,
    MonitorItem,
    MonitorProbeRun,
    ScanJob,
    User,
)
from app.db.session import get_db
from app.schemas.agent_frame import TYPE_CAPABILITIES_SET, TYPE_DISCONNECT, TYPE_UPDATE
from app.schemas.agents import (
    AgentEventRead,
    AgentLatestSample,
    AgentPatch,
    AgentPresenceRead,
    AgentRead,
    AgentSeriesPoint,
    AgentSeriesRead,
    AgentSummary,
    ApproveRequest,
    CapabilitiesUpdateRequest,
    CapabilityGrant,
    HardwareSummary,
    InstallCommandResponse,
    PairingLookupRequest,
    PairingLookupResponse,
    RevokeRequest,
    ServerKeyFleetAdoption,
    ServerKeyPendingAgent,
    ServerKeyRotationStatus,
    TLSPinPendingAgent,
    TLSPinRotateRequest,
    TLSPinRotationStatus,
    UpdateRequest,
)
from app.schemas.discovery import (
    AgentDiscoveryRead,
    DiscoveryLimits,
    DiscoveryProfileOut,
    DiscoveryReadinessRow,
    DiscoveryScopeEntry,
    ScanJobOut,
)
from app.schemas.monitor import (
    AgentProbeAssignment,
    AgentProbesRead,
    EligibleProbeAgent,
)
from app.services import (
    agent_capabilities,
    agent_discovery,
    agent_enrollment,
    agent_registry,
    agent_tls_pin,
    agent_update,
    certificate_service,
    discovery_eligibility,
    discovery_service,
    monitor_service,
)
from app.services.monitoring import probe_eligibility

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

# Fleet sparkline series ("/metrics/series"). Same discipline as the history
# block above and kept here beside it for that reason rather than in
# core/constants.py: the cap is `window / bucket width`, so the three must stay
# in step — change one and the LIMIT stops matching the grid it was derived
# from. `_SERIES_FIELDS` is the subset of `_HISTORY_SUMMARY_FIELDS` that
# actually moves on a 30-minute scale; disk and temperature are head-value-only
# on the fleet table, so a per-bucket line for them would be payload nobody
# renders.
_SERIES_WINDOW = timedelta(minutes=30)
_SERIES_BUCKET_SECONDS = 75
# 24, derived rather than written down so the "cap == window / bucket width"
# relationship cannot drift if either of the two above is retuned.
_SERIES_MAX_POINTS = int(_SERIES_WINDOW.total_seconds() // _SERIES_BUCKET_SECONDS)
_SERIES_FIELDS = ("cpu_pct", "mem_pct", "net_rx_bps", "net_tx_bps")


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
    endpoint: str | None = None,
) -> Any:
    from app.core.forwarded import forwarded_base_url
    from app.services import agent_endpoints, agent_install

    # An absent `endpoint` keeps today's behaviour, so existing commands and
    # unconfigured installs are untouched. A *named* endpoint that does not
    # exist is refused rather than falling back: silently substituting a
    # different address is exactly the defect this parameter exists to fix, and
    # it would return the moment an operator deleted an endpoint whose install
    # command was still open in someone's terminal.
    if endpoint is None:
        # Not `request.url`: nginx terminates TLS and proxies in the clear, so
        # the raw scheme is http on every https deployment — and this URL is
        # written into the agent's own config as `server_url`. See
        # forwarded_base_url.
        server_url = forwarded_base_url(request)
    else:
        selected = agent_endpoints.find_endpoint(db, endpoint)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"No agent endpoint with id {endpoint!r}")
        server_url = selected["url"]

    try:
        return agent_install.build_install_command(db, server_url)
    except ValueError as exc:
        # A missing or unreadable TLS certificate is an operator-fixable
        # deployment problem, not a bug in the request. Surfacing it as a bare
        # 500 put the only explanation in the backend journal and left the UI
        # saying "unable to generate install" with nothing to act on.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _fleet_adoption(db: Session, started_at: datetime) -> ServerKeyFleetAdoption:
    """Bucket the fleet by which server key each agent last handshaked against.

    ONE aggregate query, not one per agent — same contract as _latest_samples
    above, pinned by test_rotation_status_adoption_is_one_query_regardless_of_
    fleet_size. Counting in SQL rather than loading rows keeps it independent
    of fleet size in memory as well as in round trips.

    A pin recorded before `started_at` belongs to a previous rotation and says
    nothing about this one, so it falls through to `unseen`. Revoked agents are
    excluded: they will never handshake again and would inflate `unseen`
    permanently, making a finished rollout look stuck.
    """
    successor_pinned = and_(
        Agent.server_pk_successor_pinned_at.isnot(None),
        Agent.server_pk_successor_pinned_at >= started_at,
    )
    current_pinned = and_(
        Agent.server_pk_current_pinned_at.isnot(None),
        Agent.server_pk_current_pinned_at >= started_at,
    )
    row = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(successor_pinned).label("successor"),
            func.count().filter(and_(~successor_pinned, current_pinned)).label("current"),
            func.count().filter(and_(~successor_pinned, ~current_pinned)).label("unseen"),
        ).where(Agent.status != "revoked")
    ).one()
    return ServerKeyFleetAdoption(
        total=row.total,
        successor=row.successor,
        current=row.current,
        unseen=row.unseen,
    )


def _rotation_status(
    state: agent_crypto.ServerKeyRotationState,
    db: Session | None = None,
) -> ServerKeyRotationStatus:
    fleet = None
    if state.rotation_active and state.started_at is not None and db is not None:
        fleet = _fleet_adoption(db, state.started_at)
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
        fleet=fleet,
    )


@router.get("/server-key/status", response_model=ServerKeyRotationStatus)
def get_server_key_rotation_status(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Task 28: current/successor server identity key fingerprints and
    overlap timing — never key material itself, same as `/install-command`
    above never embeds a private key."""
    return _rotation_status(agent_crypto.load_server_key_rotation_state(db), db)


@router.post("/server-key/rotate", response_model=ServerKeyRotationStatus, status_code=201)
async def post_server_key_rotate(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
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
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="agent_server_key_rotated",
        resource="agents:server-key",
        status="ok",
        details=f"overlap_expires_at={state.overlap_expires_at}",
        severity="warn",
    )
    return _rotation_status(state, db)


# Cap borrowed from the fleet-listing routes: a drill-down exists to be acted
# on, and a list longer than this is a rollout problem, not a UI problem.
_PENDING_AGENT_LIMIT = 200


@router.get("/server-key/pending", response_model=list[ServerKeyPendingAgent])
def get_server_key_pending_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Agents that have not yet authenticated with the successor server key.

    The actionable half of `/server-key/status`'s counts: an admin deciding
    whether to let an overlap window close needs the names, not just the
    number. Empty (not an error) when no rotation is in progress — "nothing to
    chase" is the same answer either way.
    """
    state = agent_crypto.load_server_key_rotation_state(db)
    if not state.rotation_active or state.started_at is None:
        return []

    started_at = state.started_at
    successor_pinned = and_(
        Agent.server_pk_successor_pinned_at.isnot(None),
        Agent.server_pk_successor_pinned_at >= started_at,
    )
    current_pinned = and_(
        Agent.server_pk_current_pinned_at.isnot(None),
        Agent.server_pk_current_pinned_at >= started_at,
    )
    rows = db.execute(
        select(
            Agent.id,
            Agent.hostname,
            Agent.name,
            Agent.last_seen_at,
            case((current_pinned, "current"), else_="unseen").label("bucket"),
        )
        .where(Agent.status != "revoked", ~successor_pinned)
        .order_by(Agent.last_seen_at.desc().nulls_last())
        .limit(_PENDING_AGENT_LIMIT)
    ).all()
    return [
        ServerKeyPendingAgent(
            id=r.id,
            hostname=r.hostname,
            name=r.name,
            last_seen_at=r.last_seen_at,
            bucket=r.bucket,
        )
        for r in rows
    ]


def _tls_pin_status(db: Session, state: agent_tls_pin.TLSPinRotationState) -> TLSPinRotationStatus:
    """Shape one rotation state for the admin surface, including the fleet
    convergence counts the certificate-activation gate reads."""
    converged, unconverged = agent_tls_pin.convergence_counts(db, state)
    pending_agents = len(agent_registry.list_agents(db, status="pending"))
    fingerprint: str | None = None
    if state.successor_pin:
        fingerprint = hashlib.sha256(state.successor_pin.encode()).hexdigest()[:32]
    return TLSPinRotationStatus(
        active=state.rotation_active,
        successor_mode=state.successor_mode,
        successor_pin_fingerprint=fingerprint,
        started_at=state.started_at,
        overlap_expires_at=state.overlap_expires_at,
        converged=converged,
        unconverged=unconverged,
        pending_agents=pending_agents,
    )


@router.get("/tls-pin/status", response_model=TLSPinRotationStatus)
def get_tls_pin_rotation_status(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Slice 4.1: the advertised successor TLS trust policy and how much of
    the fleet has confirmed it. Never returns the pin itself."""
    return _tls_pin_status(db, agent_tls_pin.load_tls_pin_rotation_state(db))


@router.post("/tls-pin/rotate", response_model=TLSPinRotationStatus, status_code=201)
async def post_tls_pin_rotate(
    body: TLSPinRotateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, require_role("admin")],
) -> Any:
    """Slice 4.1: advertise a staged certificate's trust policy as the
    successor, so the fleet accepts either leaf across the cutover.

    Start this *before* activating the certificate. Activation is gated on
    convergence (see `api/certificates.py`) precisely so the wrong order
    fails loudly instead of stranding agents.

    Rejects with 409 while a prior rotation is still advertised — one
    rotation in flight, matching the server-key endpoint beside this one.
    """
    cert = certificate_service.get_certificate(db, body.certificate_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    state = agent_tls_pin.start_tls_pin_rotation(db, cert)
    if state is None:
        raise HTTPException(
            status_code=409,
            detail="A TLS pin rotation is already active (overlap window in progress)",
        )
    await agent_registry.broadcast_tls_pin_rotate(db, state)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="agent_tls_pin_rotated",
        resource=f"agents:tls-pin:certificate:{cert.id}",
        status="ok",
        details=(
            f"domain={cert.domain} successor_mode={state.successor_mode} "
            f"overlap_expires_at={state.overlap_expires_at}"
        ),
        severity="warn",
    )
    return _tls_pin_status(db, state)


@router.get("/tls-pin/pending", response_model=list[TLSPinPendingAgent])
def get_tls_pin_pending_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    """Slice 4.1: the active agents that have not confirmed the successor
    policy — the ones activating the certificate would strand. Capped like
    the other fleet drill-downs; a longer list is a rollout problem."""
    state = agent_tls_pin.load_tls_pin_rotation_state(db)
    if not state.rotation_active or state.started_at is None:
        return []
    pending: list[TLSPinPendingAgent] = []
    for agent in agent_registry.list_agents(db, status="active"):
        pinned = agent.tls_pin_successor_pinned_at
        if pinned is not None and pinned >= state.started_at:
            continue
        seen = agent.tls_pin_current_pinned_at
        pending.append(
            TLSPinPendingAgent(
                id=agent.id,
                hostname=agent.hostname,
                name=agent.name,
                last_seen_at=agent.last_seen_at,
                bucket=("current" if seen is not None and seen >= state.started_at else "unseen"),
            )
        )
        if len(pending) >= _PENDING_AGENT_LIMIT:
            break
    return pending


def _latest_samples(db: Session, agent_ids: list[int]) -> dict[int, AgentLatestSample]:
    """The newest host sample for every agent in the fleet, in **one** query.

    `DISTINCT ON (agent_id) ... ORDER BY agent_id, collected_at DESC` is the
    whole trick: PostgreSQL walks the existing composite index
    `ix_agent_host_samples_agent_time` (`db/models.py:570`) and keeps the first
    row it meets per agent, so the cost is independent of how much history each
    agent has retained. No new index, no new collection, no schema change.

    The query count must not scale with fleet size — the entire justification
    for hanging `latest` off the bulk presence read rather than making the page
    call `/{agent_id}/telemetry` per row. A later change to one-query-per-agent
    would produce a byte-identical response and only get slower as fleets grow,
    which is why a test pins the count instead of the payload.

    Only the summary columns are selected — never `AgentHostSample.raw` and
    never the ORM entity, which would drag that JSONB payload along with it.
    The eight fields are exactly `AgentLatestSample`'s, which is why the history
    tuple can be reused here rather than restated.
    """
    if not agent_ids:
        return {}
    rows = db.execute(
        select(
            AgentHostSample.agent_id,
            AgentHostSample.collected_at,
            *(getattr(AgentHostSample, field) for field in _HISTORY_SUMMARY_FIELDS),
        )
        .distinct(AgentHostSample.agent_id)
        .where(AgentHostSample.agent_id.in_(agent_ids))
        .order_by(AgentHostSample.agent_id, AgentHostSample.collected_at.desc())
    ).all()
    return {
        row.agent_id: AgentLatestSample(
            collected_at=row.collected_at,
            **{field: getattr(row, field) for field in _HISTORY_SUMMARY_FIELDS},
        )
        for row in rows
    }


def _load_presence_agents(db: Session, ids: list[int] | None) -> list[Agent]:
    """The fleet (or the explicit `ids` subset) for `GET /agents/presence`.

    Split out of the handler so the blocking `Session` read runs in the
    threadpool instead of on the event loop (route slice 2.5). Same single
    statement it always was.
    """
    stmt = select(Agent)
    if ids is not None:
        stmt = stmt.where(Agent.id.in_(ids))
    return list(db.execute(stmt).scalars())


def _load_presence_context(
    db: Session, agents: list[Agent]
) -> tuple[
    dict[int, dict[str, dict[str, Any]]],
    dict[int, AgentLatestSample],
    dict[int, Hardware],
]:
    """Grants, newest host sample, and linked hardware for a loaded fleet.

    Everything `GET /agents/presence` still needs from the database once
    presence itself has been resolved out of Redis. Extracted so it can run in
    the threadpool, and deliberately kept to a **fixed** statement count
    regardless of fleet size — `test_presence_query_count_does_not_scale_with_
    fleet_size` asserts exactly that, so a rewrite into per-agent reads here
    would be caught rather than merely slow.
    """
    agent_ids = [agent.id for agent in agents]
    grants = agent_registry.bulk_structured_grants_dict(db, agent_ids)
    # One DISTINCT ON for the whole fleet, hoisted out of the response
    # comprehension so the head metric values cost one query rather than one
    # per row.
    latest_by_agent = _latest_samples(db, agent_ids)

    hardware_ids = {agent.hardware_id for agent in agents if agent.hardware_id is not None}
    hardware_by_id: dict[int, Hardware] = {}
    if hardware_ids:
        hardware_by_id = {
            hw.id: hw
            for hw in db.execute(select(Hardware).where(Hardware.id.in_(hardware_ids))).scalars()
        }
    return grants, latest_by_agent, hardware_by_id


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

    agents = await run_in_threadpool(_load_presence_agents, db, ids)
    agent_ids = [agent.id for agent in agents]

    presence = await agent_registry.bulk_presence(agent_ids)

    # The three remaining reads run as one threadpool hop rather than three:
    # they are sequential against the same `Session`, which is not safe to use
    # concurrently, so there is nothing to gain from splitting them and one
    # hop costs one context switch instead of three.
    grants, latest_by_agent, hardware_by_id = await run_in_threadpool(
        _load_presence_context, db, agents
    )

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
            # Absent from the map = the agent has stored no host sample at all.
            # That stays `None` all the way to the client, which renders
            # "telemetry off" — never `0%`, which would read as a healthy host.
            latest=latest_by_agent.get(agent.id),
            # Straight off the already-loaded `Agent` row: no extra query, and
            # `None` ("never reported") stays distinct from 0 ("drained").
            spool_depth=agent.spool_depth,
            spool_bytes=agent.spool_bytes,
            spool_reported_at=agent.spool_reported_at,
        )
        for agent in agents
    ]


def _series_window_start() -> datetime:
    """The oldest instant `/metrics/series` reads, floored onto the same epoch
    grid the aggregate groups on.

    A bare `utcnow() - _SERIES_WINDOW` would straddle that grid: the window is
    exactly `_SERIES_MAX_POINTS` bucket widths wide, so an unaligned start
    leaves a *partial* bucket at both ends and a densely sampling agent
    legitimately produces one bucket more than the cap — at which point the
    LIMIT below stops being a safety net and starts deleting real points.
    Flooring the start makes the window exactly `_SERIES_MAX_POINTS` whole
    buckets, the newest of which is the partly filled one we are standing in.

    Alignment is to the epoch itself, same as `epoch_bucket`, so two requests
    seconds apart agree on the boundaries instead of sliding under the client.
    """
    seconds_since_epoch = int(utcnow().timestamp())
    newest_bucket_start = datetime.fromtimestamp(
        seconds_since_epoch // _SERIES_BUCKET_SECONDS * _SERIES_BUCKET_SECONDS, tz=UTC
    )
    oldest_bucket_offset = (_SERIES_MAX_POINTS - 1) * _SERIES_BUCKET_SECONDS
    return newest_bucket_start - timedelta(seconds=oldest_bucket_offset)


def _series_point_cap(db: Session, ids: list[int] | None) -> int:
    """The series response's hard point cap, to be applied as a SQL `LIMIT`.

    `_series_window_start` bounds each agent to `_SERIES_MAX_POINTS` buckets *by
    construction*, so this LIMIT can never truncate a legitimate response. It
    exists so the payload cannot grow with the agents' sample cadence — the
    same discipline `/telemetry/history` applies with `_HISTORY_MAX_POINTS`,
    and the reason it is a LIMIT rather than a Python slice: a slice would
    still have the database build and ship the oversized result first.

    An explicit `ids` list already states the fleet size; without one it costs a
    single `count(*)` scalar — one cheap extra query for the request, never one
    per agent.
    """
    if ids is not None:
        return _SERIES_MAX_POINTS * len(ids)
    agent_count = db.execute(select(func.count()).select_from(Agent)).scalar_one()
    return _SERIES_MAX_POINTS * agent_count


@router.get("/metrics/series", response_model=list[AgentSeriesRead])
def get_agents_metrics_series(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
    ids: Annotated[list[int] | None, Query()] = None,
) -> Any:
    """A 30-minute, 75s-bucketed series per agent — the fleet table's sparkline
    column, aggregated entirely in SQL exactly like `/telemetry/history`.

    Declared here, immediately after "/presence" and far above "/{agent_id}",
    so "metrics" isn't parsed as an agent id — same as "/pending",
    "/install-command" and "/presence" above.

    A route of its own rather than a flag on "/presence" precisely because the
    two have different cadences: the head values refresh every 30s and this
    every 120s, so folding them together would mean paying the aggregate's cost
    on every fast tick. A 30-minute *shape* is visually indistinguishable two
    minutes later; the head value beside it is what has to stay current.

    `ids=[]` (present but empty) returns no rows, distinct from omitting `ids`
    entirely (whole fleet) — the same convention "/presence" uses.

    Agents with no samples in the window are simply absent from the response
    rather than carrying an empty `points` list: the client reads a missing
    agent as an empty series and draws nothing, which is what an agent that
    just came online should look like.
    """
    if ids is not None and not ids:
        return []

    start = _series_window_start()
    bucket = epoch_bucket(AgentHostSample.collected_at, _SERIES_BUCKET_SECONDS).label("bucket")
    # Both the agent filter and the time range stay on the sample table so
    # `ix_agent_host_samples_agent_time` (and hypertable chunk exclusion, where
    # TimescaleDB is installed) still applies to the scan.
    window = [AgentHostSample.collected_at >= start]
    if ids is not None:
        window.append(AgentHostSample.agent_id.in_(ids))

    aggregate = (
        select(
            AgentHostSample.agent_id,
            bucket,
            *(func.avg(getattr(AgentHostSample, field)).label(field) for field in _SERIES_FIELDS),
        )
        .where(*window)
        .group_by(AgentHostSample.agent_id, bucket)
        .order_by(AgentHostSample.agent_id, bucket)
        .limit(_series_point_cap(db, ids))
    )

    # Averaging in the database means raw samples — and the `raw` JSONB payload
    # with them — are never materialized, however dense an agent's cadence is.
    points_by_agent: dict[int, list[AgentSeriesPoint]] = defaultdict(list)
    for row in db.execute(aggregate).all():
        points_by_agent[row.agent_id].append(
            AgentSeriesPoint(
                collected_at=row.bucket,
                # `avg()` over an integer column comes back as Decimal; `_as_float`
                # makes it a plain JSON number and keeps a NULL average as a gap.
                **{field: _as_float(getattr(row, field)) for field in _SERIES_FIELDS},
            )
        )
    return [
        AgentSeriesRead(agent_id=agent_id, points=points)
        for agent_id, points in points_by_agent.items()
    ]


# ── Slice 3 §7: probe vantages ───────────────────────────────────────────────


def _active_run_counts(db: Session, agent_ids: list[int]) -> dict[int, int]:
    """Runs each agent currently holds — §2's concurrency, measured server-side.

    The two statuses here are exactly the ones `uq_monitor_probe_runs_active`
    covers, so this counts leases the agent is still expected to answer for
    rather than everything it has ever been sent.
    """
    if not agent_ids:
        return {}
    rows = db.execute(
        select(MonitorProbeRun.agent_id, func.count())
        .where(
            MonitorProbeRun.agent_id.in_(agent_ids),
            MonitorProbeRun.status.in_(("queued", "dispatched")),
        )
        .group_by(MonitorProbeRun.agent_id)
    ).all()
    return {agent_id: count for agent_id, count in rows}


def _assigned_counts(db: Session, agent_ids: list[int]) -> dict[int, int]:
    if not agent_ids:
        return {}
    rows = db.execute(
        select(MonitorItem.probe_agent_id, func.count())
        .where(MonitorItem.probe_agent_id.in_(agent_ids))
        .group_by(MonitorItem.probe_agent_id)
    ).all()
    return {agent_id: count for agent_id, count in rows}


def _max_concurrent(grant: dict[str, Any] | None) -> int:
    """The grant's configured concurrency, defaults merged in by
    `structured_grants_dict` — never a bare `grant.config`, which is `{}` for
    every agent approved before `remote_probe` had a schema."""
    config = (grant or {}).get("config") or {}
    value = config.get("max_concurrent")
    return int(value) if isinstance(value, int) else 0


@router.get("/probe-eligible", response_model=list[EligibleProbeAgent])
async def get_probe_eligible_agents(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
    monitor_id: Annotated[int | None, Query()] = None,
    host: Annotated[str | None, Query()] = None,
    check_type: Annotated[str, Query()] = "icmp",
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[int | None, Query()] = None,
) -> Any:
    """§7's eligible-agent listing: every active agent, judged against one
    destination.

    Scope compatibility is a property of the *pair*, not of the agent, so a
    destination is required — either an existing `monitor_id` or an explicit
    `host` (plus optional `check_type`/target, which decide which readiness
    collector and which tenant apply). Without one there is nothing to answer.

    Declared before "/{agent_id}" so "probe-eligible" isn't parsed as an agent
    id, same as "/pending", "/capability-defaults" and "/presence" above.

    Every row is rendered whether or not it is eligible: §7's selector shows why
    an agent cannot be chosen, and the reason is `probe_eligibility`'s
    machine-readable vocabulary — the same string the check-now 409 returns.
    """
    if monitor_id is not None:
        probe_subject = db.get(MonitorItem, monitor_id)
        if probe_subject is None:
            raise HTTPException(status_code=404, detail="Monitor not found")
    elif host:
        # Transient and never added to the session: it exists only to give the
        # one shared evaluator the shape it takes, so an assignment is judged by
        # exactly the code that will judge the dispatch.
        probe_subject = MonitorItem(
            host=host,
            check_type=check_type,
            target_type=target_type,
            target_id=target_id,
        )
    else:
        raise HTTPException(status_code=422, detail="Either monitor_id or host is required")

    # Resolved once for the whole listing rather than once per agent: every
    # candidate is judged against the same answer set, which is also what makes
    # the per-agent scope verdicts comparable.
    resolved = list(await probe_eligibility.default_resolver(probe_subject.host))

    async def _shared_resolver(_host: str) -> list[str]:
        return resolved

    agents = list(db.execute(select(Agent).where(Agent.status == "active")).scalars())
    agent_ids = [agent.id for agent in agents]
    grants = agent_registry.bulk_structured_grants_dict(db, agent_ids)
    active_runs = _active_run_counts(db, agent_ids)
    assigned = _assigned_counts(db, agent_ids)
    collector = probe_eligibility.READINESS_COLLECTORS.get(probe_subject.check_type)
    readiness: dict[int, str] = {}
    if collector is not None and agent_ids:
        readiness = {
            row.agent_id: row.state
            for row in db.execute(
                select(AgentCapabilityReadiness).where(
                    AgentCapabilityReadiness.agent_id.in_(agent_ids),
                    AgentCapabilityReadiness.collector == collector,
                )
            ).scalars()
        }

    rows = []
    for agent in agents:
        grant = grants[agent.id].get(probe_eligibility.CAPABILITY)
        scope = probe_eligibility.derive_agent_scope(db, agent.id, (grant or {}).get("config"))
        decision = await probe_eligibility.evaluate_eligibility(
            db, probe_subject, agent_id=agent.id, resolver=_shared_resolver
        )
        rows.append(
            EligibleProbeAgent(
                agent_id=agent.id,
                name=agent.name,
                online=await agent_registry.is_agent_online(agent.id),
                granted=bool((grant or {}).get("enabled")),
                readiness=readiness.get(agent.id),
                readiness_collector=collector,
                max_concurrent=_max_concurrent(grant),
                active_runs=active_runs.get(agent.id, 0),
                assigned_monitors=assigned.get(agent.id, 0),
                scope_version=scope.version,
                scope_networks=list(scope.networks),
                excluded_networks=list(scope.excluded_networks),
                # Answered independently of `eligible`: eligibility
                # short-circuits on the first failing precondition, so an
                # offline agent would otherwise report a scope verdict that was
                # never computed.
                in_scope=agent_scope.evaluate(scope, probe_subject.host, resolved).allowed,
                eligible=decision.ok,
                reason=decision.reason,
            )
        )
    return rows


@router.get("/{agent_id}/probes", response_model=AgentProbesRead)
def get_agent_probes(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_scope("read", "*")],
) -> Any:
    """§7's Assigned Probes section: what this vantage is responsible for.

    Target state (`status`) and execution condition (`probe_execution_*`) are
    returned side by side and never folded into one another — the UP/DOWN pill
    shows target state only, and a monitor whose agent is offline keeps its last
    known target state (§2, D-12).

    This is a monitor read, so it carries the same `read` scope and tenant rule
    as `/monitors` — a scoped token without `read` cannot enumerate a vantage's
    assignments, and rows the reader could not fetch directly are not listed
    here either.
    """
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    grant = agent_registry.structured_grants_dict(db, agent_id).get(probe_eligibility.CAPABILITY)
    items = [
        item
        for item in db.execute(
            select(MonitorItem)
            .where(MonitorItem.probe_agent_id == agent_id)
            .order_by(MonitorItem.name, MonitorItem.id)
        ).scalars()
        if monitor_service.reader_can_access_monitor(
            db, user, {"target_type": item.target_type, "target_id": item.target_id}
        )
    ]
    return AgentProbesRead(
        agent_id=agent_id,
        max_concurrent=_max_concurrent(grant),
        active_runs=_active_run_counts(db, [agent_id]).get(agent_id, 0),
        assignments=[
            AgentProbeAssignment(
                monitor_id=item.id,
                name=item.name,
                check_type=item.check_type,
                host=item.host,
                target_type=item.target_type,
                target_id=item.target_id,
                interval_secs=item.interval_secs,
                enabled=item.enabled,
                status=item.last_status or "pending",
                probe_execution_status=item.probe_execution_status,
                probe_execution_reason=item.probe_execution_reason,
                probe_last_dispatched_at=item.probe_last_dispatched_at,
                probe_last_result_at=item.probe_last_result_at,
            )
            for item in items
        ],
    )


# ── §6's "Discovery scope" section (Task 26) ─────────────────────────────────

#: How much job history the section shows. A bounded page, not the whole record:
#: `DiscoveryHistoryPage` is where an operator goes for that, and this list
#: exists so the last few runs are visible without leaving the agent.
_RECENT_DISCOVERY_JOBS = 20

#: The statuses that mean an agent still owes an answer. `queued` counts because
#: D-5 parks an unreachable agent's job there with `waiting_for_agent` — it is
#: outstanding work against this vantage point, not a finished one.
_OPEN_JOB_STATUSES = ("queued", "running")

_PROVENANCE_AUTOMATIC = "automatic"
_PROVENANCE_OVERRIDE = "override"
_PROVENANCE_EXCLUDED = "excluded"


def _discovery_scope_entries(scope: agent_scope.EffectiveScope) -> list[DiscoveryScopeEntry]:
    """Plan §6's scope table: every CIDR once, with its origin and its verdict.

    Order is automatic, then override, then exclusion, because that is the order
    an operator reasons about them in — what the agent found, what an
    administrator added, what an administrator took away.

    An excluded CIDR that is *also* directly connected is rendered once, as
    `automatic`, and its exclusion shows up as `effective = False` with reason
    `excluded_cidr`. Listing it twice would suggest two independent settings; the
    control the section offers for it is the same one either way.
    """
    entries: list[DiscoveryScopeEntry] = []
    seen: set[str] = set()

    def _add(cidr: str, provenance: str) -> None:
        if cidr in seen:
            return
        seen.add(cidr)
        decision = agent_scope.network_in_scope(scope, cidr)
        entries.append(
            DiscoveryScopeEntry(
                cidr=cidr,
                provenance=provenance,
                effective=decision.allowed,
                reason=decision.reason,
            )
        )

    direct = set(scope.direct_networks)
    for cidr in scope.direct_networks:
        _add(cidr, _PROVENANCE_AUTOMATIC)
    for cidr in scope.networks:
        if cidr not in direct:
            _add(cidr, _PROVENANCE_OVERRIDE)
    for cidr in scope.excluded_networks:
        _add(cidr, _PROVENANCE_EXCLUDED)
    return entries


def _grant_int(config: Mapping[str, Any], key: str) -> int:
    """One integer grant setting, or 0 for anything that is not one.

    Tolerant on purpose, matching `discovery_service.granted_address_ceiling` and
    `granted_tcp_ports`: `_structured_grant` merges the registry default over the
    *stored* value without re-normalizing it, so this renders whatever is on the
    row. A malformed legacy value must show as 0 on a detail page, never turn the
    page into a 500. `True` is an `int` and is excluded for the reason the
    capability normalizer excludes it.
    """
    value = config.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _discovery_limits(config: dict[str, Any]) -> DiscoveryLimits:
    """The grant's bounds, with the registry defaults merged in.

    Merged here rather than trusted from the caller because an agent that holds
    no `local_discovery` row at all resolves an empty config, and the section
    should still show what the defaults would give it once granted.
    """
    defaults = agent_capabilities.default_config_for(discovery_eligibility.CAPABILITY)
    merged = defaults | config
    return DiscoveryLimits(
        scope_mode=str(merged.get("scope_mode") or ""),
        max_addresses_per_job=discovery_service.granted_address_ceiling(merged),
        max_concurrent_hosts=_grant_int(merged, "max_concurrent_hosts"),
        host_timeout_ms=_grant_int(merged, "host_timeout_ms"),
        job_timeout_seconds=_grant_int(merged, "job_timeout_seconds"),
        tcp_ports=sorted(discovery_service.granted_tcp_ports(merged)),
    )


def _discovery_readiness_rows(db: Session, agent_id: int) -> list[DiscoveryReadinessRow]:
    """Every D-8 collector, whether or not it has ever reported.

    A missing row is rendered with `state = None` rather than omitted: it is what
    makes a job refuse with `readiness_unknown`, and an operator who cannot see
    the collector at all has no way to connect the two.
    """
    stored = {
        row.collector: row
        for row in db.execute(
            select(AgentCapabilityReadiness).where(
                AgentCapabilityReadiness.agent_id == agent_id,
                AgentCapabilityReadiness.collector.in_(discovery_eligibility.READINESS_COLLECTORS),
            )
        ).scalars()
    }
    cutoff = utcnow() - timedelta(seconds=discovery_eligibility.READINESS_MAX_AGE_S)
    rows = []
    for collector in discovery_eligibility.READINESS_COLLECTORS:
        row = stored.get(collector)
        rows.append(
            DiscoveryReadinessRow(
                collector=collector,
                state=row.state if row is not None else None,
                reason=row.reason if row is not None else None,
                remediation=row.remediation if row is not None else None,
                updated_at=row.updated_at if row is not None else None,
                stale=bool(row is not None and (row.updated_at is None or row.updated_at < cutoff)),
                required=collector in discovery_eligibility.REQUIRED_READINESS_COLLECTORS,
            )
        )
    return rows


async def _agent_discovery_read(db: Session, agent_id: int) -> AgentDiscoveryRead:
    """§6's Discovery scope section: what this vantage point is discovering.

    `GET /{agent_id}/probes`' counterpart, loaded by the same page in the same
    way. It answers one question — what is being discovered from here, and if
    nothing, why — so the eligibility verdict, both pause scopes and the
    collector readiness rows are returned alongside the scope rather than left to
    three more round trips that could each disagree with the others.

    The verdict is asked with no targets and `require_online=False`: this is a
    question about the *agent*, and D-5 makes reachability a scheduling condition
    (an offline agent's job parks as `waiting_for_agent`) rather than a
    configuration error. `online` is reported separately so the page can say so.
    """
    grant = agent_registry.structured_grants_dict(db, agent_id).get(
        discovery_eligibility.CAPABILITY
    )
    config = (grant or {}).get("config") or {}
    scope = discovery_eligibility.derive_discovery_scope(db, agent_id, config)
    decision = await discovery_eligibility.evaluate_eligibility(db, agent_id, require_online=False)

    jobs = list(
        db.execute(
            select(ScanJob)
            .where(ScanJob.scan_agent_id == agent_id)
            .order_by(ScanJob.created_at.desc(), ScanJob.id.desc())
            .limit(_RECENT_DISCOVERY_JOBS)
        ).scalars()
    )
    open_jobs = list(
        db.execute(
            select(ScanJob)
            .where(ScanJob.scan_agent_id == agent_id, ScanJob.status.in_(_OPEN_JOB_STATUSES))
            .order_by(ScanJob.created_at.desc(), ScanJob.id.desc())
        ).scalars()
    )
    profiles = list(
        db.execute(
            select(DiscoveryProfile)
            .where(DiscoveryProfile.scan_agent_id == agent_id)
            .order_by(DiscoveryProfile.name, DiscoveryProfile.id)
        ).scalars()
    )

    return AgentDiscoveryRead(
        agent_id=agent_id,
        online=await agent_registry.is_agent_online(agent_id),
        granted=bool((grant or {}).get("enabled")),
        paused=bool(config.get(discovery_service.AGENT_DISCOVERY_PAUSE_KEY) is True),
        globally_paused=discovery_service.global_agent_discovery_paused(db),
        eligible=decision.ok,
        reason=decision.reason,
        detail=decision.detail,
        scope_version=scope.version,
        scope=_discovery_scope_entries(scope),
        limits=_discovery_limits(config),
        readiness=_discovery_readiness_rows(db, agent_id),
        active_jobs=[ScanJobOut.model_validate(job) for job in open_jobs],
        # The whole recent page, open jobs included: "recent" is the history list
        # and hiding the running one from it would make the newest row jump into
        # place when it finished.
        recent_jobs=[ScanJobOut.model_validate(job) for job in jobs],
        profiles=[DiscoveryProfileOut.model_validate(profile) for profile in profiles],
    )


@router.get("/{agent_id}/discovery", response_model=AgentDiscoveryRead)
async def get_agent_discovery(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("viewer")],
) -> Any:
    """The section itself. The body is shared with the pause/resume routes below
    so a hold answers with exactly the state the page would have re-fetched."""
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _agent_discovery_read(db, agent_id)


def _discovery_pause_flag(db: Session, agent_id: int) -> bool:
    """The agent's `auto_discovery_paused` hold as the scheduler reads it.

    `is True` and not truthiness, matching `discovery_service.paused_agent_ids`:
    the normalizer stores a real boolean (Task 3), and agreeing with the reader
    that actually withholds the crons is what makes a "did this change?"
    comparison here mean the same thing as "does the schedule change?".

    An agent with no `local_discovery` grant row at all resolves `False` — it has
    no automatic discovery to hold.
    """
    grant = agent_registry.structured_grants_dict(db, agent_id).get(
        discovery_eligibility.CAPABILITY
    )
    config = (grant or {}).get("config") or {}
    return config.get(discovery_service.AGENT_DISCOVERY_PAUSE_KEY) is True


async def _set_agent_discovery_pause(
    db: Session, agent_id: int, *, paused: bool, actor_user_id: int
) -> AgentDiscoveryRead:
    """M14's per-agent hold, written where Task 3 put it: the grant config.

    A grant write rather than a column of its own because that is already the
    per-agent settings store the UI edits, the registry normalizes and
    `capabilities.set` carries — and because `discovery_service.paused_agent_ids`,
    which is what actually withholds the crons, reads it there.

    Three things this is deliberately **not**:

    * It is not a capability disable. D-14 retires every in-flight dispatch the
      moment `local_discovery` goes off; a pause cancels nothing, which is why
      `put_capabilities`' cancellation arms are not reached from here.
    * It does not touch `enabled`, which is read off the stored grant and written
      back unchanged. An agent with no `local_discovery` row at all resolves
      `False` and stays ungranted — pausing something that is not running is a
      no-op the response reports honestly as `granted: false`.
    * It does not rewrite the rest of the config: `set_capability_grants` merges a
      partial config over the stored one, so `tcp_ports` and the scope lists
      survive. Handing it a full config assembled here would silently reset every
      setting the request did not mention.

    `reload_discovery_jobs` is what applies it — that function rebuilds the whole
    discovery schedule from `profiles_due_for_scheduling`, which is where all
    three pause scopes are read (Task 25).
    """
    grants = agent_registry.structured_grants_dict(db, agent_id)
    enabled = bool((grants.get(discovery_eligibility.CAPABILITY) or {}).get("enabled"))
    agent_registry.set_capability_grants(
        db,
        agent_id,
        {
            discovery_eligibility.CAPABILITY: {
                "enabled": enabled,
                "config": {discovery_service.AGENT_DISCOVERY_PAUSE_KEY: paused},
            }
        },
        actor_user_id=actor_user_id,
    )
    db.commit()
    reload_discovery_jobs(db)
    # The agent has no use for the flag (it is a server-side scheduling control),
    # but its view of its own grant must stay byte-identical to the server's, so
    # the same push `put_capabilities` makes is made here. Never raises.
    await agent_registry.publish_agent_control_frame(
        agent_id,
        {
            "type": TYPE_CAPABILITIES_SET,
            "payload": agent_registry.structured_grants_dict(db, agent_id),
        },
    )
    return await _agent_discovery_read(db, agent_id)


@router.post("/{agent_id}/discovery/pause", response_model=AgentDiscoveryRead)
async def pause_agent_discovery(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    """Hold this agent's automatic discovery (plan §6). Deletes and cancels nothing."""
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _set_agent_discovery_pause(db, agent_id, paused=True, actor_user_id=user.id)


@router.post("/{agent_id}/discovery/resume", response_model=AgentDiscoveryRead)
async def resume_agent_discovery(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    if agent_registry.get_agent(db, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _set_agent_discovery_pause(db, agent_id, paused=False, actor_user_id=user.id)


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
    if not payload.reason or len(payload.reason.strip()) < 3:
        raise HTTPException(status_code=422, detail="A revoke reason is required")
    agent = agent_registry.revoke_agent(db, agent_id, actor_user_id=user.id, reason=payload.reason)
    # §8: a revoked agent's runs are cancelled and its assignments are kept as
    # unavailable. The agent-initiated path (agent_link._handle_uninstall) does
    # exactly the same thing through the same helper — the two must not diverge,
    # since either one leaves the same runs holding the same partial unique
    # index.
    cancellation = monitor_service.cancel_agent_probe_runs(
        db, agent_id, reason=monitor_service.CANCEL_AGENT_REVOKED
    )
    # Slice 4 D-14, and the same argument one slice later: a revoked agent's
    # discovery dispatches are closed here, in this transaction, because from the
    # moment the status flips `dispatch_frame`'s grant gate drops the agent's own
    # terminal summary and nothing else would ever close them. D-4 has no
    # `agent_revoked`; `agent_unavailable` is what a job whose executor no longer
    # exists failed for, and it is what `discovery_eligibility`'s `agent_inactive`
    # already maps onto at dispatch time.
    discovery_cancellation = agent_discovery.cancel_agent_dispatches(
        db, agent_id, reason=agent_discovery.ERROR_AGENT_UNAVAILABLE
    )
    from app.services.log_service import write_log

    write_log(
        db=db,
        action="agent_revoke_authorized",
        entity_type="agent",
        entity_id=agent_id,
        entity_name=agent.name or agent.hostname or agent.fingerprint,
        actor_id=user.id,
        actor_name=user.display_name or user.email,
        severity="warn",
        category="audit",
        diff={
            "reason": payload.reason,
            "probe_runs_cancelled": len(cancellation.cancels),
            "discovery_dispatches_cancelled": len(discovery_cancellation.cancels),
        },
    )
    db.commit()
    await agent_registry.broadcast_presence(agent_id, "revoked")
    # Before the disconnect below, not after: an agent that is about to lose its
    # socket should still get the chance to stop work it will never be able to
    # report on.
    await monitor_service.publish_probe_cancels(cancellation)
    await agent_discovery.publish_discovery_cancels(discovery_cancellation)
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
    was_granted = agent_registry.grants_dict(db, agent_id).get(probe_eligibility.CAPABILITY, False)
    # D-16's second scope trigger. Read *before* the write, because the version
    # is derived from the grant's `scope_mode`/`excluded_cidrs`/`additional_cidrs`
    # as well as from what the agent reported, and after the write there is
    # nothing left to compare against.
    was_discovering = agent_registry.grants_dict(db, agent_id).get(
        agent_discovery.CAPABILITY, False
    )
    # Phase D. `auto_discovery_paused` is an ordinary client-settable key of the
    # `local_discovery` grant (Task 3), so this route is a *second* writer of the
    # same hold `POST /{id}/discovery/pause` writes — and a hold has to be
    # effective when it is written, whichever route wrote it. The flag is read
    # once per `reload_discovery_jobs`, by
    # `discovery_service.profiles_due_for_scheduling`. A write that did not
    # rebuild the schedule would be accepted, reported back as paused, and leave
    # `next_scheduled` advertising runs that
    # `discovery_service.profile_scheduling_held` would refuse at fire time — the
    # second line of the gate, not a substitute for this one. Read before the
    # write, like
    # `was_discovering` above: `set_capability_grants` merges the new config over
    # the stored one, so afterwards there is nothing left to compare against.
    was_discovery_paused = _discovery_pause_flag(db, agent_id)
    agent_registry.set_capability_grants(db, agent_id, payload.capabilities, actor_user_id=user.id)
    # §8's capability-disable row, and it has to happen *here* rather than being
    # left to the result path: from the moment the grant is off,
    # agent_link.dispatch_frame's gate (a bare grants_dict lookup) drops any
    # probe.result as a capability_violation, so a still-open run would never be
    # closed by the agent's own answer — it would hold
    # uq_monitor_probe_runs_active until the reconciliation pass expired it.
    cancellation = monitor_service.ProbeCancellation()
    if was_granted and not agent_registry.grants_dict(db, agent_id).get(
        probe_eligibility.CAPABILITY, False
    ):
        cancellation = monitor_service.cancel_agent_probe_runs(
            db, agent_id, reason=monitor_service.CANCEL_CAPABILITY_DISABLED
        )
    # Slice 4 D-14/D-16, and for the same reason the probe half above sits here:
    # once `local_discovery` is off, `dispatch_frame`'s gate drops the agent's own
    # terminal summary as a `capability_violation`, so a dispatch nobody closed
    # stays open until Task 23's pass expires it. A grant that is still on but
    # whose scope moved is the other half of the same edit —
    # `cancel_scope_changed_dispatches` re-derives the version and retires only
    # the dispatches whose snapshot no longer matches, so an unrelated setting
    # change (a smaller `max_concurrent_hosts`, say) retires nothing.
    still_discovering = agent_registry.grants_dict(db, agent_id).get(
        agent_discovery.CAPABILITY, False
    )
    if was_discovering and not still_discovering:
        discovery_cancellation = agent_discovery.cancel_agent_dispatches(
            db, agent_id, reason=agent_discovery.ERROR_CAPABILITY_DISABLED
        )
    elif still_discovering:
        discovery_cancellation = agent_discovery.cancel_scope_changed_dispatches(db, agent_id)
    else:
        discovery_cancellation = agent_discovery.DiscoveryCancellation()
    db.commit()
    # Same order as the dedicated pause route: commit, then rebuild, so the
    # rebuild derives the schedule from durable state. Conditional on the flag
    # having actually moved, because `reload_discovery_jobs` tears down and
    # re-registers *every* discovery cron in the installation — a fleet-wide cost
    # that a capability edit changing nothing the schedule is derived from (a
    # narrower `tcp_ports`, say) should not pay.
    if _discovery_pause_flag(db, agent_id) != was_discovery_paused:
        reload_discovery_jobs(db)
    await monitor_service.publish_probe_cancels(cancellation)
    await agent_discovery.publish_discovery_cancels(discovery_cancellation)
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


#: How many dependent profile names a 409 spells out before summarizing the rest.
#: A bounded message: a fleet-wide profile set could otherwise put hundreds of
#: names into an error toast.
_DELETE_CONFLICT_NAME_LIMIT = 10


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> None:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    # §8: deletion is blocked while assignments remain. `monitor_items.
    # probe_agent_id` is the one agents FK declared RESTRICT rather than
    # CASCADE, so without this pre-check the delete would surface as an
    # unhandled IntegrityError and a 500 — and the operator would learn nothing
    # about which monitors are in the way. Unassigning is a decision they make
    # explicitly, never a side effect of deleting the vantage.
    assigned = db.execute(
        select(func.count()).select_from(MonitorItem).where(MonitorItem.probe_agent_id == agent_id)
    ).scalar_one()
    if assigned:
        raise HTTPException(
            status_code=409,
            detail=f"{assigned} monitor(s) are still assigned to this agent",
        )
    # D-1's other live assignment. `discovery_profiles.scan_agent_id` is the one
    # Slice 4 FK declared RESTRICT — a profile names where its scans *will* run,
    # so deleting the vantage point out from under it would leave a profile that
    # can never execute. `scan_jobs.scan_agent_id` and
    # `scan_results.discovery_agent_id` are CASCADE and deliberately not counted
    # here: they are finished history, and an agent that ever ran a scan would
    # otherwise be permanently undeletable (the retention purge is disabled
    # outright when `discovery_retention_days <= 0`).
    #
    # The names, not just the count: repointing a profile at another agent is an
    # explicit decision, and an operator cannot make it from a number.
    profile_names = list(
        db.execute(
            select(DiscoveryProfile.name)
            .where(DiscoveryProfile.scan_agent_id == agent_id)
            .order_by(DiscoveryProfile.name, DiscoveryProfile.id)
            .limit(_DELETE_CONFLICT_NAME_LIMIT)
        ).scalars()
    )
    profile_count = db.execute(
        select(func.count())
        .select_from(DiscoveryProfile)
        .where(DiscoveryProfile.scan_agent_id == agent_id)
    ).scalar_one()
    if profile_count:
        listed = ", ".join(profile_names)
        if profile_count > len(profile_names):
            listed += f" and {profile_count - len(profile_names)} more"
        raise HTTPException(
            status_code=409,
            detail=(f"{profile_count} discovery profile(s) still scan from this agent: {listed}"),
        )
    from app.services.log_service import write_log

    write_log(
        db=db,
        action="agent_delete_authorized",
        entity_type="agent",
        entity_id=agent_id,
        entity_name=agent.name or agent.hostname or agent.fingerprint,
        actor_id=user.id,
        actor_name=user.display_name or user.email,
        severity="warn",
        category="audit",
        diff={"status": agent.status},
    )
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


# Registered BEFORE get_binary, and the order is load-bearing. Starlette
# matches in registration order and a `{str}` path parameter accepts dots, so
# `/binary/1.2.3/linux/amd64.sig` matches the route below with
# arch="amd64.sig" if that route is reached first. `binary_path` would then
# resolve the .sig file quite happily, so this endpoint would *appear* to
# work while being dead code — and its 404-on-missing-signature behavior,
# which is what tells an agent "this build is unsigned" rather than "this
# version does not exist", would never run.
@binary_router.get("/binary/{version}/{os_name}/{arch}.sig")
def get_binary_signature(version: str, os_name: str, arch: str) -> FileResponse:
    """Slice 4.2: the detached Ed25519 signature over the binary below.

    Unauthenticated, like the binary route beside it, and for a stronger
    reason: the signature *is* the integrity mechanism. Route auth would add
    nothing an attacker who can serve the binary could not also defeat, and
    the agent has no user session to present.
    """
    try:
        path = agent_update.binary_signature_path(version, os_name, arch)
    except ValueError:
        raise HTTPException(status_code=404, detail="Signature not found") from None
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No signature for {os_name}/{arch} at version {version}",
        )
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@binary_router.get("/binary/{version}/{os_name}/{arch}")
def get_binary(version: str, os_name: str, arch: str) -> FileResponse:
    try:
        path = agent_update.binary_path(version, os_name, arch)
    except ValueError:
        raise HTTPException(status_code=404, detail="Binary not found") from None
    if not path.exists():
        raise HTTPException(status_code=404, detail="Binary not found")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)
