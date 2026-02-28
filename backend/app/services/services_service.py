from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.core.errors import NotFoundError, ConflictError
from app.db.models import Service, ServiceDependency, ServiceStorage, ServiceMisc, EntityTag, Tag
from app.schemas.services import ServiceCreate, ServiceUpdate


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    existing = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
    for et in existing:
        db.delete(et)
    db.flush()
    for name in tag_names:
        tag = db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(EntityTag(entity_type=entity_type, entity_id=entity_id, tag_id=tag.id))


def get_tags_for(db: Session, entity_type: str, entity_id: int) -> list[str]:
    rows = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
    return [row.tag.name for row in rows]


def _to_dict(db: Session, svc: Service) -> dict:
    d = {c.name: getattr(svc, c.name) for c in svc.__table__.columns}
    d["tags"] = get_tags_for(db, "service", svc.id)
    return d


def list_services(
    db: Session,
    *,
    compute_id: int | None = None,
    hardware_id: int | None = None,
    category: str | None = None,
    environment: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Service)
    if compute_id:
        stmt = stmt.where(Service.compute_id == compute_id)
    if hardware_id:
        stmt = stmt.where(Service.hardware_id == hardware_id)
    if category:
        stmt = stmt.where(Service.category == category)
    if environment:
        stmt = stmt.where(Service.environment == environment)
    if q:
        stmt = stmt.where(or_(Service.name.ilike(f"%{q}%"), Service.description.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == "service") & (EntityTag.entity_id == Service.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_service(db: Session, service_id: int) -> dict:
    svc = db.get(Service, service_id)
    if svc is None:
        raise NotFoundError(f"Service {service_id} not found")
    return _to_dict(db, svc)


def create_service(db: Session, payload: ServiceCreate) -> dict:
    svc = Service(
        name=payload.name,
        slug=payload.slug,
        compute_id=payload.compute_id,
        hardware_id=payload.hardware_id,
        icon_slug=payload.icon_slug,
        category=payload.category,
        url=payload.url,
        ports=payload.ports,
        description=payload.description,
        environment=payload.environment,
    )
    db.add(svc)
    db.flush()
    _sync_tags(db, "service", svc.id, payload.tags)
    db.commit()
    db.refresh(svc)
    return _to_dict(db, svc)


def update_service(db: Session, service_id: int, payload: ServiceUpdate) -> dict:
    svc = db.get(Service, service_id)
    if svc is None:
        raise NotFoundError(f"Service {service_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(svc, field, value)
    svc.updated_at = datetime.now(timezone.utc)
    if payload.tags is not None:
        _sync_tags(db, "service", svc.id, payload.tags)
    db.commit()
    db.refresh(svc)
    return _to_dict(db, svc)


def delete_service(db: Session, service_id: int) -> None:
    svc = db.get(Service, service_id)
    if svc is None:
        raise NotFoundError(f"Service {service_id} not found")
    # Remove entity tags
    _sync_tags(db, "service", svc.id, [])
    # Remove dependency rows referencing this service on either side
    for dep in list(db.execute(
        select(ServiceDependency).where(
            (ServiceDependency.service_id == svc.id) |
            (ServiceDependency.depends_on_id == svc.id)
        )
    ).scalars().all()):
        db.delete(dep)
    # Remove storage and misc links
    for link in list(db.execute(
        select(ServiceStorage).where(ServiceStorage.service_id == svc.id)
    ).scalars().all()):
        db.delete(link)
    for link in list(db.execute(
        select(ServiceMisc).where(ServiceMisc.service_id == svc.id)
    ).scalars().all()):
        db.delete(link)
    db.flush()
    db.delete(svc)
    db.commit()


# ── Dependencies ─────────────────────────────────────────────────────────────


def get_dependencies(db: Session, service_id: int) -> list[ServiceDependency]:
    return list(
        db.execute(select(ServiceDependency).where(ServiceDependency.service_id == service_id))
        .scalars()
        .all()
    )


def add_dependency(db: Session, service_id: int, depends_on_id: int) -> ServiceDependency:
    if db.get(Service, service_id) is None:
        raise NotFoundError(f"Service {service_id} not found")
    if db.get(Service, depends_on_id) is None:
        raise NotFoundError(f"Service {depends_on_id} not found")
    dep = ServiceDependency(service_id=service_id, depends_on_id=depends_on_id)
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return dep


def remove_dependency(db: Session, service_id: int, depends_on_id: int) -> None:
    dep = db.execute(
        select(ServiceDependency).where(
            ServiceDependency.service_id == service_id,
            ServiceDependency.depends_on_id == depends_on_id,
        )
    ).scalar_one_or_none()
    if dep is None:
        raise NotFoundError("Dependency not found")
    db.delete(dep)
    db.commit()


# ── Storage links ─────────────────────────────────────────────────────────────


def get_service_storage(db: Session, service_id: int) -> list[ServiceStorage]:
    return list(
        db.execute(select(ServiceStorage).where(ServiceStorage.service_id == service_id))
        .scalars()
        .all()
    )


def add_storage_link(db: Session, service_id: int, storage_id: int, purpose: str | None) -> ServiceStorage:
    if db.get(Service, service_id) is None:
        raise NotFoundError(f"Service {service_id} not found")
    link = ServiceStorage(service_id=service_id, storage_id=storage_id, purpose=purpose)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove_storage_link(db: Session, service_id: int, storage_id: int) -> None:
    link = db.execute(
        select(ServiceStorage).where(
            ServiceStorage.service_id == service_id,
            ServiceStorage.storage_id == storage_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("Storage link not found")
    db.delete(link)
    db.commit()


# ── Misc links ────────────────────────────────────────────────────────────────


def get_service_misc(db: Session, service_id: int) -> list[ServiceMisc]:
    return list(
        db.execute(select(ServiceMisc).where(ServiceMisc.service_id == service_id))
        .scalars()
        .all()
    )


def add_misc_link(db: Session, service_id: int, misc_id: int, purpose: str | None) -> ServiceMisc:
    if db.get(Service, service_id) is None:
        raise NotFoundError(f"Service {service_id} not found")
    link = ServiceMisc(service_id=service_id, misc_id=misc_id, purpose=purpose)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove_misc_link(db: Session, service_id: int, misc_id: int) -> None:
    link = db.execute(
        select(ServiceMisc).where(
            ServiceMisc.service_id == service_id,
            ServiceMisc.misc_id == misc_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("Misc link not found")
    db.delete(link)
    db.commit()
