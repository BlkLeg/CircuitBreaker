import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from fastapi import HTTPException

from app.db.models import Service, ServiceDependency, ServiceStorage, ServiceMisc, EntityTag, Tag, Category
from app.schemas.services import ServiceCreate, ServiceUpdate
from app.services.environments_service import resolve_environment_id
from app.services.ip_reservation import check_ip_conflict, _parse_ports_json, bulk_conflict_map
from app.services.log_service import write_log
from app.core.time import utcnow, utcnow_iso

_logger = logging.getLogger(__name__)


def _resolve_category(db: Session, category_id: int | None, category_str: str | None) -> int | None:
    """Return the category_id to use, creating from category string if needed."""
    if category_id is not None:
        return category_id
    if category_str:
        existing = db.execute(
            select(Category).where(Category.name == category_str)
        ).scalar_one_or_none()
        if existing:
            return existing.id
        cat = Category(name=category_str, created_at=utcnow_iso())
        db.add(cat)
        db.flush()
        return cat.id
    return None


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


def _backfill_ports_json(db: Session) -> None:
    """Backfill ports_json for services that have a legacy freeform ports string.

    Parses tokens like "80/tcp,443/tcp" into a structured JSON array and writes
    the result into the ports_json column.  Rows where ports is NULL or
    ports_json is already set are skipped.
    """
    import re as _re
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT id, ports FROM services WHERE ports IS NOT NULL AND ports_json IS NULL")
    ).fetchall()
    for svc_id, ports_str in rows:
        entries = []
        for token in [t.strip() for t in ports_str.split(",") if t.strip()]:
            m = _re.match(r"^(\d+)/(\w+)$", token)
            if m:
                entries.append({"port": int(m.group(1)), "protocol": m.group(2), "ip": None})
            elif _re.match(r"^\d+$", token):
                entries.append({"port": int(token), "protocol": "tcp", "ip": None})
            else:
                entries.append({"port": None, "protocol": None, "ip": None, "raw": token})
        db.execute(
            text("UPDATE services SET ports_json = :val WHERE id = :id"),
            {"val": json.dumps(entries), "id": svc_id},
        )
    db.commit()


def _ports_to_json(ports_list) -> str | None:
    """Serialise a list of PortEntry objects (or dicts) to JSON for storage."""
    if ports_list is None:
        return None
    entries = []
    for pe in ports_list:
        if hasattr(pe, "model_dump"):
            entries.append(pe.model_dump())
        else:
            entries.append(dict(pe))
    return json.dumps(entries)


def _to_dict(db: Session, svc: Service) -> dict:
    d = {c.name: getattr(svc, c.name) for c in svc.__table__.columns}
    # Expose structured ports from ports_json, overriding the legacy plain-text ports field
    raw_ports_json = d.pop("ports_json", None)
    try:
        d["ports"] = json.loads(raw_ports_json) if raw_ports_json else None
    except (json.JSONDecodeError, TypeError):
        d["ports"] = None
    d["tags"] = get_tags_for(db, "service", svc.id)
    d["category_name"] = svc.category_rel.name if svc.category_rel else None
    d["environment_name"] = svc.environment_rel.name if svc.environment_rel else None
    return d


def list_services(
    db: Session,
    *,
    compute_id: int | None = None,
    hardware_id: int | None = None,
    category: str | None = None,
    environment: str | None = None,
    environment_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Service)
    if compute_id:
        stmt = stmt.where(Service.compute_id == compute_id)
    if hardware_id:
        stmt = stmt.where(Service.hardware_id == hardware_id)
    if category:
        stmt = stmt.join(Category, Category.id == Service.category_id).where(
            Category.name.ilike(category)
        )
    if environment_id is not None:
        stmt = stmt.where(Service.environment_id == environment_id)
    elif environment:
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
    conflict_map = bulk_conflict_map(db)
    result = []
    for r in rows:
        d = _to_dict(db, r)
        d["ip_conflict"] = conflict_map.get(("service", r.id), False)
        result.append(d)
    return result


def get_service(db: Session, service_id: int) -> dict:
    svc = db.get(Service, service_id)
    if svc is None:
        raise ValueError(f"Service {service_id} not found")
    d = _to_dict(db, svc)
    if svc.ip_address:
        existing_ports = _parse_ports_json(svc.ports_json)
        conflicts = check_ip_conflict(
            db,
            ip=svc.ip_address,
            ports=existing_ports,
            exclude_entity_type="service",
            exclude_entity_id=service_id,
        )
        d["ip_conflict"] = len(conflicts) > 0
        d["ip_conflict_details"] = [c.to_dict() for c in conflicts]
    else:
        d["ip_conflict"] = False
        d["ip_conflict_details"] = []
    return d


def create_service(db: Session, payload: ServiceCreate) -> dict:
    if payload.ip_address:
        ports_as_dicts = [pe.model_dump() for pe in payload.ports] if payload.ports else None
        conflicts = check_ip_conflict(
            db,
            ip=payload.ip_address,
            ports=ports_as_dicts,
            exclude_entity_type="service",
            exclude_entity_id=None,
            incoming_entity_type="service",
        )
        # Only block on service-to-service port clashes; hardware/compute IP
        # matches are reported in the conflict list but don't block creation
        # (a service is allowed to share an IP with its hosting hardware).
        blocking_conflicts = [c for c in conflicts if c.entity_type == "service"]
        if blocking_conflicts:
            _logger.warning(
                "IP conflict blocked save for service %r: %s already used by %s",
                payload.name,
                payload.ip_address,
                ", ".join(c.entity_name for c in conflicts),
            )
            write_log(
                db,
                action="ip_conflict",
                entity_type="service",
                entity_name=payload.name,
                severity="warn",
                details=f"IP conflict for {payload.ip_address}: already used by {', '.join(c.entity_name for c in conflicts)}",
                category="crud",
            )
            raise HTTPException(
                status_code=409,
                detail={"detail": "IP conflict detected", "conflicts": [c.to_dict() for c in conflicts]},
            )
    resolved_cat_id = _resolve_category(db, payload.category_id, payload.category)
    resolved_env_id = resolve_environment_id(db, payload.environment_id, payload.environment)
    ports_json = _ports_to_json(payload.ports)
    svc = Service(
        name=payload.name,
        slug=payload.slug,
        compute_id=payload.compute_id,
        hardware_id=payload.hardware_id,
        icon_slug=payload.icon_slug,
        url=payload.url,
        ports_json=ports_json,
        description=payload.description,
        environment=payload.environment,
        environment_id=resolved_env_id,
        status=payload.status,
        ip_address=payload.ip_address,
        category_id=resolved_cat_id,
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
        raise ValueError(f"Service {service_id} not found")
    # Determine effective IP and ports for conflict check
    effective_ip = payload.ip_address if payload.ip_address is not None else svc.ip_address
    if effective_ip:
        if payload.ports is not None:
            ports_for_check = [pe.model_dump() for pe in payload.ports]
        else:
            # Use existing ports if not being updated
            ports_for_check = _parse_ports_json(svc.ports_json)
        conflicts = check_ip_conflict(
            db,
            ip=effective_ip,
            ports=ports_for_check,
            exclude_entity_type="service",
            exclude_entity_id=service_id,
            incoming_entity_type="service",
        )
        if conflicts:
            _logger.warning(
                "IP conflict blocked save for service %r: %s already used by %s",
                svc.name,
                effective_ip,
                ", ".join(c.entity_name for c in conflicts),
            )
            raise HTTPException(
                status_code=409,
                detail={"detail": "IP conflict detected", "conflicts": [c.to_dict() for c in conflicts]},
            )
    data = payload.model_dump(exclude_unset=True, exclude={"tags"})
    cat_str = data.pop("category", None)
    cat_id = data.pop("category_id", None)
    if cat_str is not None or cat_id is not None:
        data["category_id"] = _resolve_category(db, cat_id, cat_str)
    env_str = data.pop("environment", None)
    env_id = data.pop("environment_id", None)
    if env_str is not None or env_id is not None:
        data["environment_id"] = resolve_environment_id(db, env_id, env_str)
        if env_str is not None:
            data["environment"] = env_str
    # Convert structured ports list to ports_json; remove "ports" from generic setattr loop
    if "ports" in data:
        ports_list = data.pop("ports")
        data["ports_json"] = _ports_to_json(ports_list)
    for field, value in data.items():
        setattr(svc, field, value)
    svc.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "service", svc.id, payload.tags)
    db.commit()
    db.refresh(svc)
    return _to_dict(db, svc)


def delete_service(db: Session, service_id: int) -> None:
    svc = db.get(Service, service_id)
    if svc is None:
        raise ValueError(f"Service {service_id} not found")
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
        raise ValueError(f"Service {service_id} not found")
    if db.get(Service, depends_on_id) is None:
        raise ValueError(f"Service {depends_on_id} not found")
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
        raise ValueError("Dependency not found")
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
        raise ValueError(f"Service {service_id} not found")
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
        raise ValueError("Storage link not found")
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
        raise ValueError(f"Service {service_id} not found")
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
        raise ValueError("Misc link not found")
    db.delete(link)
    db.commit()
