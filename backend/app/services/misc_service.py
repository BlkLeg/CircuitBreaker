from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.db.models import MiscItem, EntityTag, Tag
from app.schemas.misc import MiscItemCreate, MiscItemUpdate


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


def _to_dict(db: Session, item: MiscItem) -> dict:
    d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    d["tags"] = get_tags_for(db, "misc", item.id)
    return d


def list_misc(
    db: Session,
    *,
    kind: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(MiscItem)
    if kind:
        stmt = stmt.where(MiscItem.kind == kind)
    if q:
        stmt = stmt.where(or_(MiscItem.name.ilike(f"%{q}%"), MiscItem.description.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == "misc") & (EntityTag.entity_id == MiscItem.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_misc_item(db: Session, item_id: int) -> dict:
    item = db.get(MiscItem, item_id)
    if item is None:
        raise ValueError(f"MiscItem {item_id} not found")
    return _to_dict(db, item)


def create_misc_item(db: Session, payload: MiscItemCreate) -> dict:
    item = MiscItem(
        name=payload.name,
        kind=payload.kind,
        url=payload.url,
        description=payload.description,
    )
    db.add(item)
    db.flush()
    _sync_tags(db, "misc", item.id, payload.tags)
    db.commit()
    db.refresh(item)
    return _to_dict(db, item)


def update_misc_item(db: Session, item_id: int, payload: MiscItemUpdate) -> dict:
    item = db.get(MiscItem, item_id)
    if item is None:
        raise ValueError(f"MiscItem {item_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    if payload.tags is not None:
        _sync_tags(db, "misc", item.id, payload.tags)
    db.commit()
    db.refresh(item)
    return _to_dict(db, item)


def delete_misc_item(db: Session, item_id: int) -> None:
    item = db.get(MiscItem, item_id)
    if item is None:
        raise ValueError(f"MiscItem {item_id} not found")
    _sync_tags(db, "misc", item.id, [])
    db.delete(item)
    db.commit()
