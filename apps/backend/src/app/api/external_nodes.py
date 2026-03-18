from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.external_nodes import (
    ExternalNodeCreate,
    ExternalNodeNetworkLink,
    ExternalNodeNetworkRead,
    ExternalNodeRead,
    ExternalNodeUpdate,
    ServiceExternalNodeRead,
)
from app.services import external_nodes_service as svc

router = APIRouter(tags=["external-nodes"])


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ExternalNodeRead])
def list_external_nodes(
    environment: str | None = Query(None),
    provider: str | None = Query(None),
    kind: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    return svc.list_external_nodes(
        db,
        environment=environment,
        provider=provider,
        kind=kind,
        q=q,
        tag=tag,
    )


@router.post("", response_model=ExternalNodeRead, status_code=201)
def create_external_node(
    payload: ExternalNodeCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = svc.create_external_node(db, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A record with this identifier already exists."
        ) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="external_node_created",
        resource=f"external_node:{result.id}",
        status="ok",
    )
    return result


@router.get("/{node_id}", response_model=ExternalNodeRead)
def get_external_node(node_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return svc.get_external_node(db, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{node_id}", response_model=ExternalNodeRead)
def patch_external_node(
    node_id: int,
    payload: ExternalNodeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = svc.update_external_node(db, node_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A record with this identifier already exists."
        ) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="external_node_updated",
        resource=f"external_node:{node_id}",
        status="ok",
    )
    return result


@router.delete("/{node_id}", status_code=204)
def delete_external_node(
    node_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    try:
        svc.delete_external_node(db, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="external_node_deleted",
        resource=f"external_node:{node_id}",
        status="ok",
        severity="warn",
    )


# ── Network relationships ────────────────────────────────────────────────────


@router.get("/{node_id}/networks", response_model=list[ExternalNodeNetworkRead])
def list_networks(node_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return svc.list_networks_for_node(db, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{node_id}/networks", response_model=ExternalNodeNetworkRead, status_code=201)
def link_network(
    node_id: int,
    payload: ExternalNodeNetworkLink,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = svc.link_network(db, node_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This link already exists.") from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="external_node_network_linked",
        resource=f"external_node:{node_id}",
        status="ok",
    )
    return result


# ── Service relationships ────────────────────────────────────────────────────


@router.get("/{node_id}/services", response_model=list[ServiceExternalNodeRead])
def list_services(node_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return svc.list_services_for_node(db, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Standalone relationship deletes (by relation_id) ─────────────────────────

# These use a separate APIRouter to avoid path prefix issues

_rel_router = APIRouter(tags=["external-nodes"])


@_rel_router.delete("/external-node-networks/{relation_id}", status_code=204)
def unlink_network(
    relation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    try:
        svc.unlink_network(db, relation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="external_node_network_unlinked",
        resource=f"external_node_network:{relation_id}",
        status="ok",
        severity="warn",
    )


@_rel_router.delete("/service-external-nodes/{relation_id}", status_code=204)
def unlink_service(
    relation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    try:
        svc.unlink_service(db, relation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="service_external_node_unlinked",
        resource=f"service_external_node:{relation_id}",
        status="ok",
        severity="warn",
    )
