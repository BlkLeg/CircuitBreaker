import logging

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeNetwork, ComputeUnit, EntityTag, Service, Tag
from app.schemas.compute_units import ComputeUnitCreate, ComputeUnitUpdate
from app.services.environments_service import resolve_environment_id
from app.services.ip_reservation import bulk_conflict_map, check_ip_conflict, resolve_ip_conflict

_logger = logging.getLogger(__name__)


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    existing = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
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
    rows = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    return [row.tag.name for row in rows]


def _to_dict(db: Session, cu: ComputeUnit) -> dict:
    mapper = sa_inspect(type(cu))
    d = {attr.key: getattr(cu, attr.key) for attr in mapper.column_attrs}
    d["tags"] = get_tags_for(db, "compute", cu.id)
    # Aggregate storage pools from services hosted on this compute unit
    pools: list[str] = []
    for svc in cu.services or []:
        for link in svc.storage_links or []:
            if link.storage and link.storage.name not in pools:
                pools.append(link.storage.name)
    if cu.disk_gb or pools:
        d["storage_allocated"] = {"disk_gb": cu.disk_gb, "storage_pools": pools}
    else:
        d["storage_allocated"] = None
    d["environment_name"] = cu.environment_rel.name if cu.environment_rel else None
    return d


def list_compute_units(
    db: Session,
    *,
    kind: str | None = None,
    hardware_id: int | None = None,
    environment: str | None = None,
    environment_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(ComputeUnit)
    if kind:
        stmt = stmt.where(ComputeUnit.kind == kind)
    if hardware_id:
        stmt = stmt.where(ComputeUnit.hardware_id == hardware_id)
    if environment_id is not None:
        stmt = stmt.where(ComputeUnit.environment_id == environment_id)
    elif environment:
        stmt = stmt.where(ComputeUnit.environment == environment)
    if q:
        stmt = stmt.where(or_(ComputeUnit.name.ilike(f"%{q}%"), ComputeUnit.notes.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(
                EntityTag,
                (EntityTag.entity_type == "compute") & (EntityTag.entity_id == ComputeUnit.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    conflict_map = bulk_conflict_map(db)
    result = []
    for r in rows:
        d = _to_dict(db, r)
        d["ip_conflict"] = conflict_map.get(("compute_unit", r.id), False)
        result.append(d)
    return result


def get_compute_unit(db: Session, cu_id: int) -> dict:
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        raise ValueError(f"ComputeUnit {cu_id} not found")
    d = _to_dict(db, cu)
    if cu.ip_address:
        conflicts = check_ip_conflict(
            db,
            ip=cu.ip_address,
            ports=None,
            exclude_entity_type="compute_unit",
            exclude_entity_id=cu_id,
        )
        d["ip_conflict"] = len(conflicts) > 0
        d["ip_conflict_details"] = [c.to_dict() for c in conflicts]
    else:
        d["ip_conflict"] = False
        d["ip_conflict_details"] = []
    return d


def create_compute_unit(db: Session, payload: ComputeUnitCreate) -> dict:
    if payload.ip_address:
        conflicts = check_ip_conflict(
            db,
            ip=payload.ip_address,
            ports=None,
            exclude_entity_type="compute_unit",
            exclude_entity_id=None,
        )
        if conflicts:
            _logger.warning(
                "IP conflict blocked save for compute_unit %r: %s already used by %s",
                payload.name,
                payload.ip_address,
                ", ".join(c.entity_name for c in conflicts),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "IP conflict detected",
                    "conflicts": [c.to_dict() for c in conflicts],
                },
            )
    resolved_env_id = resolve_environment_id(db, payload.environment_id, payload.environment)
    cu = ComputeUnit(
        name=payload.name,
        kind=payload.kind,
        hardware_id=payload.hardware_id,
        os=payload.os,
        icon_slug=payload.icon_slug,
        cpu_cores=payload.cpu_cores,
        memory_mb=payload.memory_mb,
        disk_gb=payload.disk_gb,
        ip_address=payload.ip_address,
        download_speed_mbps=payload.download_speed_mbps,
        upload_speed_mbps=payload.upload_speed_mbps,
        cpu_brand=payload.cpu_brand,
        environment=payload.environment,
        environment_id=resolved_env_id,
        notes=payload.notes,
    )
    db.add(cu)
    db.flush()
    _sync_tags(db, "compute", cu.id, payload.tags)
    db.commit()
    db.refresh(cu)
    return _to_dict(db, cu)


def update_compute_unit(db: Session, cu_id: int, payload: ComputeUnitUpdate) -> dict:
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        raise ValueError(f"ComputeUnit {cu_id} not found")
    effective_ip = payload.ip_address if payload.ip_address is not None else cu.ip_address
    if effective_ip:
        conflicts = check_ip_conflict(
            db,
            ip=effective_ip,
            ports=None,
            exclude_entity_type="compute_unit",
            exclude_entity_id=cu_id,
        )
        if conflicts:
            _logger.warning(
                "IP conflict blocked save for compute_unit %r: %s already used by %s",
                cu.name,
                effective_ip,
                ", ".join(c.entity_name for c in conflicts),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "IP conflict detected",
                    "conflicts": [c.to_dict() for c in conflicts],
                },
            )
    data = payload.model_dump(exclude_unset=True, exclude={"tags"})
    env_str = data.pop("environment", None)
    env_id = data.pop("environment_id", None)
    if env_str is not None or env_id is not None:
        data["environment_id"] = resolve_environment_id(db, env_id, env_str)
        if env_str is not None:
            data["environment"] = env_str
    for field, value in data.items():
        setattr(cu, field, value)
    old_hardware_id = cu.hardware_id
    cu.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "compute", cu.id, payload.tags)
    db.commit()
    db.refresh(cu)
    # Re-evaluate IP conflict state for all services on this compute unit
    affected = db.execute(select(Service).where(Service.compute_id == cu_id)).scalars().all()
    for svc in affected:
        result = resolve_ip_conflict(db, svc.id, svc.ip_address, svc.compute_id, svc.hardware_id)
        svc.ip_mode = result["ip_mode"]
        svc.ip_conflict = result["is_conflict"]
        svc.ip_conflict_json = result["conflict_with"]
    # CB-REL-002: cascade hardware_id change to services on this compute unit
    new_hardware_id = cu.hardware_id
    if new_hardware_id != old_hardware_id:
        for svc in affected:
            svc.hardware_id = new_hardware_id
    if affected:
        db.commit()
    # CB-STATE-002: recalculate own compute status (respects status_override)
    from app.services.status_service import recalculate_compute_status, recalculate_hardware_status

    recalculate_compute_status(db, cu_id)
    # CB-STATE-001: recalculate hardware status for parent hardware
    if cu.hardware_id:
        recalculate_hardware_status(db, cu.hardware_id)
    db.commit()
    return _to_dict(db, cu)


def delete_compute_unit(db: Session, cu_id: int) -> None:
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        raise ValueError(f"ComputeUnit {cu_id} not found")
    # Block if services are still running on this compute unit
    svc_count = db.execute(select(Service).where(Service.compute_id == cu_id)).scalars().all()
    if svc_count:
        names = ", ".join(s.name for s in svc_count)
        raise ValueError(
            f"Cannot delete: {len(svc_count)} service(s) are running on this compute unit ({names}). "
            "Remove or reassign them first."
        )
    # Cascade-remove network memberships (join table, safe to auto-remove)
    for row in (
        db.execute(select(ComputeNetwork).where(ComputeNetwork.compute_id == cu_id)).scalars().all()
    ):
        db.delete(row)
    db.flush()
    _sync_tags(db, "compute", cu.id, [])
    db.delete(cu)
    db.commit()
