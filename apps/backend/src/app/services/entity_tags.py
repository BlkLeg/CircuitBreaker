"""Tag and document attachment, shared by every entity service.

Tags and docs attach to anything through `entity_tags` / `entity_docs`, which
key on a `(entity_type, entity_id)` pair rather than a foreign key. That makes
the read and write for them identical for hardware, services, storage,
networks, compute units, misc items and external nodes — and it was copied,
byte for byte, into all seven service modules.

Copies of a query are not a style problem: `sync_tags` deletes every existing
row before re-adding, so a fix to its flush ordering or its tag upsert had to
land in seven places or the entity whose service was missed would silently
behave differently from the rest.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Doc, EntityDoc, EntityTag, Tag


def sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    """Replace an entity's tags with `tag_names`, creating any tag that is new.

    Deletes and re-adds rather than diffing: the row set is small, and a
    replace is what every caller wants. Flushes between the delete and the
    inserts so a tag being re-applied does not collide with its own old row.
    """
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
    """Every tag name attached to an entity."""
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


def get_documents_for(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    """Docs attached to an entity, most recently updated first.

    Selects the four display columns rather than whole `Doc` rows: this feeds a
    list in the entity's detail payload, and the bodies are large.
    """
    rows = db.execute(
        select(Doc.id, Doc.title, Doc.category, Doc.icon)
        .join(EntityDoc, EntityDoc.doc_id == Doc.id)
        .where(EntityDoc.entity_type == entity_type, EntityDoc.entity_id == entity_id)
        .order_by(Doc.updated_at.desc())
    ).all()
    return [
        {
            "id": doc_id,
            "title": title,
            "category": category,
            "icon": icon,
        }
        for doc_id, title, category, icon in rows
    ]
