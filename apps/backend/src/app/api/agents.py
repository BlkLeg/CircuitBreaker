from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role
from app.db.models import Agent, AgentEvent, Hardware, User
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
    HardwareSummary,
    InstallCommandResponse,
    PairingLookupRequest,
    PairingLookupResponse,
    RevokeRequest,
    UpdateRequest,
)
from app.services import agent_enrollment, agent_registry, agent_update

router = APIRouter(tags=["agents"])


def _to_read(db: Session, agent: Agent) -> AgentRead:
    data = AgentRead.model_validate(agent)
    data.capabilities = agent_registry.grants_dict(db, agent.id)
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


@router.get("/install-command", response_model=InstallCommandResponse)
def get_install_command(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, require_role("admin")],
) -> Any:
    from app.services import agent_install

    server_url = f"{request.url.scheme}://{request.url.netloc}"
    return agent_install.build_install_command(db, server_url)


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
    grants = agent_registry.bulk_grants_dict(db, agent_ids)

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
            capabilities=grants[agent.id],
            hardware=(
                HardwareSummary.model_validate(hardware_by_id[agent.hardware_id])
                if agent.hardware_id in hardware_by_id
                else None
            ),
        )
        for agent in agents
    ]


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
        {"type": TYPE_CAPABILITIES_SET, "payload": agent_registry.grants_dict(db, agent_id)},
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
