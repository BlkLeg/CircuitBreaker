from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.clusters import (
    HardwareClusterCreate,
    HardwareClusterUpdate,
    HardwareClusterMemberLink,
    HardwareClusterMemberUpdate,
)
from app.services import clusters_service

router = APIRouter(tags=["hardware-clusters"])


# ── Cluster CRUD ─────────────────────────────────────────────────────────────

@router.get("")
def list_clusters(
    environment: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return clusters_service.list_clusters(db, environment=environment)


@router.post("", status_code=201)
def create_cluster(
    payload: HardwareClusterCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        return clusters_service.create_cluster(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A cluster with this name already exists.")


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, db: Session = Depends(get_db)):
    try:
        return clusters_service.get_cluster(db, cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{cluster_id}")
def update_cluster(
    cluster_id: int,
    payload: HardwareClusterUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        return clusters_service.update_cluster(db, cluster_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{cluster_id}", status_code=204)
def delete_cluster(
    cluster_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        clusters_service.delete_cluster(db, cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Members ───────────────────────────────────────────────────────────────────

@router.get("/{cluster_id}/members")
def list_members(cluster_id: int, db: Session = Depends(get_db)):
    try:
        return clusters_service.list_members(db, cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{cluster_id}/members", status_code=201)
def add_member(
    cluster_id: int,
    payload: HardwareClusterMemberLink,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        return clusters_service.add_member(db, cluster_id, payload.hardware_id, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This hardware is already a member of the cluster.")


@router.patch("/{cluster_id}/members/{member_id}")
def update_member(
    cluster_id: int,
    member_id: int,
    payload: HardwareClusterMemberUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        return clusters_service.update_member(db, cluster_id, member_id, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{cluster_id}/members/{member_id}", status_code=204)
def remove_member(
    cluster_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        clusters_service.remove_member(db, cluster_id, member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
