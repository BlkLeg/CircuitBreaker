from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.networks import Network, NetworkCreate, NetworkUpdate, ComputeNetworkLink, ComputeNetworkRead
from app.services import networks_service

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("", response_model=list[Network])
def list_networks(q: str | None = Query(None), db: Session = Depends(get_db)):
    return networks_service.list_networks(db, q=q)


@router.post("", response_model=Network, status_code=201)
def create_network(payload: NetworkCreate, db: Session = Depends(get_db)):
    return networks_service.create_network(db, payload)


@router.get("/{network_id}", response_model=Network)
def get_network(network_id: int, db: Session = Depends(get_db)):
    try:
        return networks_service.get_network(db, network_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{network_id}", response_model=Network)
def patch_network(network_id: int, payload: NetworkUpdate, db: Session = Depends(get_db)):
    try:
        return networks_service.update_network(db, network_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{network_id}", status_code=204)
def delete_network(network_id: int, db: Session = Depends(get_db)):
    try:
        networks_service.delete_network(db, network_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Compute memberships ──────────────────────────────────────────────────────


@router.get("/{network_id}/members", response_model=list[ComputeNetworkRead])
def list_members(network_id: int, db: Session = Depends(get_db)):
    return networks_service.list_compute_members(db, network_id)


@router.post("/{network_id}/members", response_model=ComputeNetworkRead, status_code=201)
def add_member(network_id: int, payload: ComputeNetworkLink, db: Session = Depends(get_db)):
    try:
        return networks_service.add_compute_member(db, network_id, payload.compute_id, payload.ip_address)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{network_id}/members/{compute_id}", status_code=204)
def remove_member(network_id: int, compute_id: int, db: Session = Depends(get_db)):
    try:
        networks_service.remove_compute_member(db, network_id, compute_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
