from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import EntityTag, MiscItem, Tag
from app.schemas.inventory import PageRequest, PageResult
from app.schemas.misc import MiscItemCreate, MiscItemUpdate
from app.services.entity_tags import get_tags_for, get_tags_for_many
from app.services.entity_tags import sync_tags as _sync_tags
from app.services.inventory_paging import escape_ilike, page_result, paginate_rows

_MISC_SORT_COLUMNS = {
    "id": MiscItem.id,
    "name": MiscItem.name,
    "kind": MiscItem.kind,
    "created_at": MiscItem.created_at,
    "updated_at": MiscItem.updated_at,
}


def _to_dict(db: Session, item: MiscItem, tags: list[str] | None = None) -> dict:
    d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    d["tags"] = tags if tags is not None else get_tags_for(db, "misc", item.id)
    return d


def _misc_filtered_statement(
    *, kind: str | None, tag: str | None, q: str | None
) -> Select[tuple[MiscItem]]:
    statement = select(MiscItem)
    if kind:
        statement = statement.where(MiscItem.kind == kind)
    if q:
        term = f"%{escape_ilike(q)}%"
        statement = statement.where(
            or_(
                MiscItem.name.ilike(term, escape="\\"),
                MiscItem.description.ilike(term, escape="\\"),
            )
        )
    if tag:
        statement = (
            statement.join(
                EntityTag, (EntityTag.entity_type == "misc") & (EntityTag.entity_id == MiscItem.id)
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    return statement


def list_misc(
    db: Session,
    *,
    kind: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = _misc_filtered_statement(kind=kind, tag=tag, q=q)
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def list_misc_page(
    db: Session,
    page: PageRequest,
    *,
    kind: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> PageResult[dict]:
    """Return a bounded misc-item page enriched without per-row tag queries."""
    filtered = _misc_filtered_statement(kind=kind, tag=tag, q=q)
    rows, total = paginate_rows(
        db,
        filtered=filtered,
        page=page,
        sort_columns=_MISC_SORT_COLUMNS,
        id_column=MiscItem.id,
    )
    tags = get_tags_for_many(db, "misc", [row.id for row in rows])
    items = [_to_dict(db, row, tags[row.id]) for row in rows]
    return page_result(items, total=total, page=page)


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
    item.updated_at = utcnow()
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
