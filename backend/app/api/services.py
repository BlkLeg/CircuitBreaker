from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.services import (
    Service,
    ServiceCreate,
    ServiceUpdate,
    ServiceDependency,
    ServiceDependencyCreate,
    ServiceStorageLink,
    ServiceStorageRead,
    ServiceMiscLink,
    ServiceMiscRead,
)
from app.services import services_service

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=list[Service])
def list_services(
    compute_id: int | None = Query(None),
    hardware_id: int | None = Query(None),
    category: str | None = Query(None),
    environment: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return services_service.list_services(
        db, compute_id=compute_id, hardware_id=hardware_id,
        category=category, environment=environment, tag=tag, q=q
    )


@router.post("", response_model=Service, status_code=201)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db)):
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
def patch_service(service_id: int, payload: ServiceUpdate, db: Session = Depends(get_db)):
    try:
        return services_service.update_service(db, service_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{service_id}", status_code=204)
def delete_service(service_id: int, db: Session = Depends(get_db)):
    try:
        services_service.delete_service(db, service_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Dependencies ─────────────────────────────────────────────────────────────


@router.get("/{service_id}/dependencies", response_model=list[ServiceDependency])
def get_dependencies(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_dependencies(db, service_id)


@router.post("/{service_id}/dependencies", response_model=ServiceDependency, status_code=201)
def add_dependency(service_id: int, payload: ServiceDependencyCreate, db: Session = Depends(get_db)):
    try:
        return services_service.add_dependency(db, service_id, payload.depends_on_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/dependencies/{depends_on_id}", status_code=204)
def remove_dependency(service_id: int, depends_on_id: int, db: Session = Depends(get_db)):
    try:
        services_service.remove_dependency(db, service_id, depends_on_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Storage links ─────────────────────────────────────────────────────────────


@router.get("/{service_id}/storage", response_model=list[ServiceStorageRead])
def get_service_storage(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_service_storage(db, service_id)


@router.post("/{service_id}/storage", response_model=ServiceStorageRead, status_code=201)
def add_storage_link(service_id: int, payload: ServiceStorageLink, db: Session = Depends(get_db)):
    try:
        return services_service.add_storage_link(db, service_id, payload.storage_id, payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/storage/{storage_id}", status_code=204)
def remove_storage_link(service_id: int, storage_id: int, db: Session = Depends(get_db)):
    try:
        services_service.remove_storage_link(db, service_id, storage_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Misc links ────────────────────────────────────────────────────────────────


@router.get("/{service_id}/misc", response_model=list[ServiceMiscRead])
def get_service_misc(service_id: int, db: Session = Depends(get_db)):
    return services_service.get_service_misc(db, service_id)


@router.post("/{service_id}/misc", response_model=ServiceMiscRead, status_code=201)
def add_misc_link(service_id: int, payload: ServiceMiscLink, db: Session = Depends(get_db)):
    try:
        return services_service.add_misc_link(db, service_id, payload.misc_id, payload.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{service_id}/misc/{misc_id}", status_code=204)
def remove_misc_link(service_id: int, misc_id: int, db: Session = Depends(get_db)):
    try:
        services_service.remove_misc_link(db, service_id, misc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
