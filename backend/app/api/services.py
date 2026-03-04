
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.external_nodes import ServiceExternalNodeLink, ServiceExternalNodeRead
from app.schemas.services import (
    Service,
    ServiceCreate,
    ServiceDependency,
    ServiceDependencyCreate,
    ServiceMiscLink,
    ServiceMiscRead,
    ServiceStorageLink,
    ServiceStorageRead,
    ServiceUpdate,
)
from app.services import external_nodes_service, services_service
from app.services.ip_reservation import resolve_ip_conflict

router = APIRouter(tags=["services"])


class ServiceIpCheckRequest(BaseModel):
    ip_address: str
    compute_id: int | None = None
    hardware_id: int | None = None
    exclude_service_id: int | None = None


@router.post("/check-ip")
def check_service_ip(payload: ServiceIpCheckRequest, db: Session = Depends(get_db)):
    return resolve_ip_conflict(
        db,
        service_id=payload.exclude_service_id,
        ip_address=payload.ip_address,
        compute_id=payload.compute_id,
        hardware_id=payload.hardware_id,
    )


@router.get("", response_model=list[Service])
def list_services(
    compute_id: int | None = Query(None),
    hardware_id: int | None = Query(None),
    category: str | None = Query(None),
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return services_service.list_services(
        db, compute_id=compute_id, hardware_id=hardware_id,
        category=category, environment=environment, environment_id=environment_id,
        tag=tag, q=q
    )


@router.post("", response_model=Service, status_code=201)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return services_service.create_service(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.get("/{service_id}", response_model=Service)
def get_service(service_id: int, db: Session = Depends(get_db)):
    try:
        return services_service.get_service(db, service_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{service_id}", response_model=Service)
def patch_service(service_id: int, payload: ServiceUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return services_service.update_service(db, service_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{service_id}", status_code=204)
def delete_service(service_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        services_service.delete_service(db, service_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete: record is still referenced by other entities.")


# ── Dependencies ─────────────────────────────────────────────────────────────


@router.get("/{service_id}/dependencies", response_model=list[ServiceDependency])
def get_dependencies(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_dependencies(db, service_id)


@router.post("/{service_id}/dependencies", response_model=ServiceDependency, status_code=201)
def add_dependency(service_id: int, payload: ServiceDependencyCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return services_service.add_dependency(db, service_id, payload.depends_on_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/dependencies/{depends_on_id}", status_code=204)
def remove_dependency(service_id: int, depends_on_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        services_service.remove_dependency(db, service_id, depends_on_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Storage links ─────────────────────────────────────────────────────────────


@router.get("/{service_id}/storage", response_model=list[ServiceStorageRead])
def get_service_storage(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_service_storage(db, service_id)


@router.post("/{service_id}/storage", response_model=ServiceStorageRead, status_code=201)
def add_storage_link(service_id: int, payload: ServiceStorageLink, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return services_service.add_storage_link(db, service_id, payload.storage_id, payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/storage/{storage_id}", status_code=204)
def remove_storage_link(service_id: int, storage_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        services_service.remove_storage_link(db, service_id, storage_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Misc links ────────────────────────────────────────────────────────────────


@router.get("/{service_id}/misc", response_model=list[ServiceMiscRead])
def get_service_misc(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_service_misc(db, service_id)


@router.post("/{service_id}/misc", response_model=ServiceMiscRead, status_code=201)
def add_misc_link(service_id: int, payload: ServiceMiscLink, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return services_service.add_misc_link(db, service_id, payload.misc_id, payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/misc/{misc_id}", status_code=204)
def remove_misc_link(service_id: int, misc_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        services_service.remove_misc_link(db, service_id, misc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── External dependency links ─────────────────────────────────────────────────


@router.get("/{service_id}/external-dependencies", response_model=list[ServiceExternalNodeRead])
def get_external_deps(service_id: int, db: Session = Depends(get_db)):
    from app.db.models import ExternalNode, ServiceExternalNode
    from app.db.models import Service as ServiceModel
    svc = db.get(ServiceModel, service_id)
    if svc is None:
        raise HTTPException(status_code=404, detail=f"Service {service_id} not found")
    from sqlalchemy import select
    links = db.execute(
        select(ServiceExternalNode).where(ServiceExternalNode.service_id == service_id)
    ).scalars().all()
    result = []
    for link in links:
        ext = db.get(ExternalNode, link.external_node_id)
        result.append({
            "id": link.id,
            "service_id": link.service_id,
            "external_node_id": link.external_node_id,
            "purpose": link.purpose,
            "external_node_name": ext.name if ext else None,
            "service_name": svc.name,
        })
    return result


@router.post("/{service_id}/external-dependencies", response_model=ServiceExternalNodeRead, status_code=201)
def add_external_dep(
    service_id: int,
    payload: ServiceExternalNodeLink,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        return external_nodes_service.link_service(db, service_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This link already exists.")


@router.delete("/{service_id}/external-dependencies/{relation_id}", status_code=204)
def remove_external_dep(service_id: int, relation_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        external_nodes_service.unlink_service(db, relation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

