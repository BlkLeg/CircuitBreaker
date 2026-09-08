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

from collections.abc import Sequence
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Doc, EntityDoc, EntityTag, Tag

_MAX_BULK_ENTITY_IDS = 1000


class DocumentSummary(TypedDict):
    """Document metadata allowed in inventory list/detail responses."""

    id: int
    title: str
    category: str
    icon: str


def _bounded_ids(entity_ids: Sequence[int]) -> list[int]:
    ids = list(dict.fromkeys(entity_ids))
    if len(ids) > _MAX_BULK_ENTITY_IDS:
        raise ValueError(f"At most {_MAX_BULK_ENTITY_IDS} entity IDs may be loaded at once")
    return ids


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
    return get_tags_for_many(db, entity_type, [entity_id])[entity_id]


def get_tags_for_many(
    db: Session, entity_type: str, entity_ids: Sequence[int]
) -> dict[int, list[str]]:
    """Load tag names for a bounded entity set in one deterministic query."""
    ids = _bounded_ids(entity_ids)
    result: dict[int, list[str]] = {entity_id: [] for entity_id in ids}
    if not ids:
        return result
    rows = db.execute(
        select(EntityTag.entity_id, Tag.name)
        .join(Tag, Tag.id == EntityTag.tag_id)
        .where(EntityTag.entity_type == entity_type, EntityTag.entity_id.in_(ids))
        .order_by(EntityTag.entity_id, func.lower(Tag.name), Tag.id)
    ).all()
    for entity_id, name in rows:
        result[entity_id].append(name)
    return result


def get_documents_for(db: Session, entity_type: str, entity_id: int) -> list[DocumentSummary]:
    """Docs attached to an entity, most recently updated first.

    Selects the four display columns rather than whole `Doc` rows: this feeds a
    list in the entity's detail payload, and the bodies are large.
    """
    return get_documents_for_many(db, entity_type, [entity_id])[entity_id]


def get_documents_for_many(
    db: Session, entity_type: str, entity_ids: Sequence[int]
) -> dict[int, list[DocumentSummary]]:
    """Load document display metadata for a bounded entity set in one query.

    Document bodies are deliberately excluded. Every requested ID is present
    in the result, including entities with no documents.
    """
    ids = _bounded_ids(entity_ids)
    result: dict[int, list[DocumentSummary]] = {entity_id: [] for entity_id in ids}
    if not ids:
        return result
    rows = db.execute(
        select(EntityDoc.entity_id, Doc.id, Doc.title, Doc.category, Doc.icon)
        .join(Doc, Doc.id == EntityDoc.doc_id)
        .where(EntityDoc.entity_type == entity_type, EntityDoc.entity_id.in_(ids))
        .order_by(EntityDoc.entity_id, Doc.updated_at.desc(), Doc.id.desc())
    ).all()
    for entity_id, doc_id, title, category, icon in rows:
        result[entity_id].append({"id": doc_id, "title": title, "category": category, "icon": icon})
    return result
