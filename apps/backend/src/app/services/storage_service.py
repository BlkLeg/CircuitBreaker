from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import EntityTag, Storage, Tag
from app.schemas.storage import StorageCreate, StorageUpdate


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


def _to_dict(db: Session, st: Storage) -> dict:
    d = {c.name: getattr(st, c.name) for c in st.__table__.columns}
    d["tags"] = get_tags_for(db, "storage", st.id)
    return d


def list_storage(
    db: Session,
    *,
    kind: str | None = None,
    hardware_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Storage)
    if kind:
        stmt = stmt.where(Storage.kind == kind)
    if hardware_id:
        stmt = stmt.where(Storage.hardware_id == hardware_id)
    if q:
        stmt = stmt.where(or_(Storage.name.ilike(f"%{q}%"), Storage.notes.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(
                EntityTag,
                (EntityTag.entity_type == "storage") & (EntityTag.entity_id == Storage.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_storage(db: Session, storage_id: int) -> dict:
    st = db.get(Storage, storage_id)
    if st is None:
        raise ValueError(f"Storage {storage_id} not found")
    return _to_dict(db, st)


def create_storage(db: Session, payload: StorageCreate) -> dict:
    st = Storage(
        name=payload.name,
        kind=payload.kind,
        hardware_id=payload.hardware_id,
        capacity_gb=payload.capacity_gb,
        path=payload.path,
        protocol=payload.protocol,
        notes=payload.notes,
    )
    db.add(st)
    db.flush()
    _sync_tags(db, "storage", st.id, payload.tags)
    db.commit()
    db.refresh(st)
    return _to_dict(db, st)


def update_storage(db: Session, storage_id: int, payload: StorageUpdate) -> dict:
    st = db.get(Storage, storage_id)
    if st is None:
        raise ValueError(f"Storage {storage_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(st, field, value)
    st.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "storage", st.id, payload.tags)
    db.commit()
    db.refresh(st)
    return _to_dict(db, st)


def delete_storage(db: Session, storage_id: int) -> None:
    st = db.get(Storage, storage_id)
    if st is None:
        raise ValueError(f"Storage {storage_id} not found")
    _sync_tags(db, "storage", st.id, [])
    db.delete(st)
    db.commit()
