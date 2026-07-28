from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role
from app.db.models import Agent, AgentEvent, User
from app.db.session import get_db
from app.schemas.agents import (
    AgentEventRead,
    AgentPatch,
    AgentRead,
    AgentSummary,
    ApproveRequest,
    CapabilitiesUpdateRequest,
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
    _user: Annotated[User, require_role("editor")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    db.flush()
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
    duplicate = False
    if agent.machine_id_hash:
        duplicate = (
            db.execute(
                select(Agent).where(
                    Agent.machine_id_hash == agent.machine_id_hash,
                    Agent.id != agent.id,
                )
            ).scalar_one_or_none()
            is not None
        )

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
        capability_overrides=payload.capabilities,
    )
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
    await agent_registry.broadcast_presence(agent_id, "rejected")
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
    await agent_registry.broadcast_presence(agent_id, "revoked")
    return _to_read(db, agent)


@router.put("/{agent_id}/capabilities", response_model=AgentRead)
def put_capabilities(
    agent_id: int,
    payload: CapabilitiesUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, require_role("admin")],
) -> Any:
    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_registry.set_capability_grants(db, agent_id, payload.capabilities, actor_user_id=user.id)
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
    db.flush()


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
    agent_registry.record_event(
        db,
        agent_id,
        "version_changed",
        actor_user_id=user.id,
        detail={"target_version": version},
    )
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
