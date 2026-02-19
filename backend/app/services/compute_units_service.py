from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, inspect as sa_inspect

from app.db.models import ComputeUnit, EntityTag, Tag
from app.schemas.compute_units import ComputeUnitCreate, ComputeUnitUpdate


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


def _to_dict(db: Session, cu: ComputeUnit) -> dict:
    mapper = sa_inspect(type(cu))
    d = {attr.key: getattr(cu, attr.key) for attr in mapper.column_attrs}
    d["tags"] = get_tags_for(db, "compute", cu.id)
    return d


def list_compute_units(
    db: Session,
    *,
    kind: str | None = None,
    hardware_id: int | None = None,
    environment: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(ComputeUnit)
    if kind:
        stmt = stmt.where(ComputeUnit.kind == kind)
    if hardware_id:
        stmt = stmt.where(ComputeUnit.hardware_id == hardware_id)
    if environment:
        stmt = stmt.where(ComputeUnit.environment == environment)
    if q:
        stmt = stmt.where(or_(ComputeUnit.name.ilike(f"%{q}%"), ComputeUnit.notes.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == "compute") & (EntityTag.entity_id == ComputeUnit.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_compute_unit(db: Session, cu_id: int) -> dict:
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        raise ValueError(f"ComputeUnit {cu_id} not found")
    return _to_dict(db, cu)


def create_compute_unit(db: Session, payload: ComputeUnitCreate) -> dict:
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
        environment=payload.environment,
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
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(cu, field, value)
    cu.updated_at = datetime.now(timezone.utc)
    if payload.tags is not None:
        _sync_tags(db, "compute", cu.id, payload.tags)
    db.commit()
    db.refresh(cu)
    return _to_dict(db, cu)


def delete_compute_unit(db: Session, cu_id: int) -> None:
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        raise ValueError(f"ComputeUnit {cu_id} not found")
    _sync_tags(db, "compute", cu.id, [])
    db.delete(cu)
    db.commit()
