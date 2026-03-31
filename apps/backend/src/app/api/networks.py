from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.networks import (
    ComputeNetworkLink,
    ComputeNetworkRead,
    HardwareNetworkLink,
    HardwareNetworkRead,
    Network,
    NetworkCreate,
    NetworkPeerCreate,
    NetworkPeerRead,
    NetworkUpdate,
)
from app.services import networks_service

router = APIRouter(tags=["networks"])


@router.get("", response_model=list[Network])
def list_networks(
    tag: str | None = Query(None),
    vlan_id: int | None = Query(None),
    cidr: str | None = Query(None),
    q: str | None = Query(None),
    gateway_hardware_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> list[Any]:
    return networks_service.list_networks(
        db,
        tag=tag,
        vlan_id=vlan_id,
        cidr=cidr,
        q=q,
        gateway_hardware_id=gateway_hardware_id,
    )


@router.post("", response_model=Network, status_code=201)
def create_network(
    payload: NetworkCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = networks_service.create_network(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Network with this name already exists"
        ) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="network_created",
        resource=f"network:{result['id']}",
        status="ok",
    )
    return result


@router.get("/{network_id}", response_model=Network)
def get_network(network_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return networks_service.get_network(db, network_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{network_id}", response_model=Network)
def patch_network(
    network_id: int,
    payload: NetworkUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = networks_service.update_network(db, network_id, payload)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="network_updated",
            resource=f"network:{network_id}",
            status="ok",
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Network with this name already exists"
        ) from exc


@router.delete("/{network_id}", status_code=204)
def delete_network(
    network_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    try:
        networks_service.delete_network(db, network_id)
        log_audit(
            db,
            request,
            user_id=user_id,
            action="network_deleted",
            resource=f"network:{network_id}",
            status="ok",
            severity="warn",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Cannot delete: other records still reference this network."
        ) from exc


# ── Compute memberships ──────────────────────────────────────────────────────


@router.get("/{network_id}/members", response_model=list[ComputeNetworkRead])
def list_members(network_id: int, db: Session = Depends(get_db)) -> list[Any]:
    return networks_service.list_compute_members(db, network_id)


@router.post("/{network_id}/members", response_model=ComputeNetworkRead, status_code=201)
def add_member(
    network_id: int,
    payload: ComputeNetworkLink,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    try:
        return networks_service.add_compute_member(
            db, network_id, payload.compute_id, payload.ip_address, payload.connection_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Compute unit is already a member of this network"
        ) from exc


@router.delete("/{network_id}/members/{compute_id}", status_code=204)
def remove_member(
    network_id: int,
    compute_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    try:
        networks_service.remove_compute_member(db, network_id, compute_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Hardware memberships ────────────────────────────────────────────


@router.get("/{network_id}/hardware-members", response_model=list[HardwareNetworkRead])
def list_hardware_members(network_id: int, db: Session = Depends(get_db)) -> list[Any]:
    return networks_service.list_hardware_members(db, network_id)


@router.post("/{network_id}/hardware-members", response_model=HardwareNetworkRead, status_code=201)
def add_hardware_member(
    network_id: int,
    payload: HardwareNetworkLink,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    try:
        return networks_service.add_hardware_member(
            db, network_id, payload.hardware_id, payload.ip_address, payload.connection_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Hardware is already a member of this network"
        ) from exc


@router.delete("/{network_id}/hardware-members/{hardware_id}", status_code=204)
def remove_hardware_member(
    network_id: int,
    hardware_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    try:
        networks_service.remove_hardware_member(db, network_id, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Network peering ──────────────────────────────────────────────────────────


@router.get("/{network_id}/peers", response_model=list[NetworkPeerRead])
def list_peers(network_id: int, db: Session = Depends(get_db)) -> list[Any]:
    return networks_service.list_peers(db, network_id)


@router.post("/{network_id}/peers", response_model=NetworkPeerRead, status_code=201)
def add_peer(
    network_id: int,
    payload: NetworkPeerCreate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    try:
        return networks_service.add_peer(
            db, network_id, payload.peer_network_id, payload.connection_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Peer relationship already exists or constraint failed."
        ) from exc


@router.delete("/{network_id}/peers/{peer_network_id}", status_code=204)
def remove_peer(
    network_id: int,
    peer_network_id: int,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> None:
    try:
        networks_service.remove_peer(db, network_id, peer_network_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
