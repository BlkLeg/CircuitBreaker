from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.db.models import Hardware, EntityTag, Tag
from app.schemas.hardware import HardwareCreate, HardwareUpdate


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    """Upsert tags and sync EntityTag rows for the given entity."""
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


def _to_dict(db: Session, hw: Hardware) -> dict:
    d = {c.name: getattr(hw, c.name) for c in hw.__table__.columns}
    d["tags"] = get_tags_for(db, "hardware", hw.id)
    return d


def list_hardware(
    db: Session,
    *,
    tag: str | None = None,
    role: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Hardware)
    if role:
        stmt = stmt.where(Hardware.role == role)
    if q:
        stmt = stmt.where(or_(Hardware.name.ilike(f"%{q}%"), Hardware.notes.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == "hardware") & (EntityTag.entity_id == Hardware.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_hardware(db: Session, hardware_id: int) -> dict:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    return _to_dict(db, hw)


def create_hardware(db: Session, payload: HardwareCreate) -> dict:
    hw = Hardware(
        name=payload.name,
        role=payload.role,
        vendor=payload.vendor,
        model=payload.model,
        cpu=payload.cpu,
        memory_gb=payload.memory_gb,
        location=payload.location,
        notes=payload.notes,
    )
    db.add(hw)
    db.flush()
    _sync_tags(db, "hardware", hw.id, payload.tags)
    db.commit()
    db.refresh(hw)
    return _to_dict(db, hw)


def update_hardware(db: Session, hardware_id: int, payload: HardwareUpdate) -> dict:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(hw, field, value)
    hw.updated_at = datetime.now(timezone.utc)
    if payload.tags is not None:
        _sync_tags(db, "hardware", hw.id, payload.tags)
    db.commit()
    db.refresh(hw)
    return _to_dict(db, hw)


def delete_hardware(db: Session, hardware_id: int) -> None:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    _sync_tags(db, "hardware", hw.id, [])
    db.delete(hw)
    db.commit()
