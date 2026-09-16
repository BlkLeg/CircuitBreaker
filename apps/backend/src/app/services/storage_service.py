from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import EntityTag, Storage, Tag
from app.schemas.inventory import PageRequest, PageResult
from app.schemas.storage import StorageCreate, StorageUpdate
from app.services.entity_tags import get_tags_for, get_tags_for_many
from app.services.entity_tags import sync_tags as _sync_tags
from app.services.inventory_paging import escape_ilike, page_result, paginate_rows

_STORAGE_SORT_COLUMNS = {
    "id": Storage.id,
    "name": Storage.name,
    "kind": Storage.kind,
    "created_at": Storage.created_at,
    "updated_at": Storage.updated_at,
    "hardware_id": Storage.hardware_id,
}


def _to_dict(db: Session, st: Storage, tags: list[str] | None = None) -> dict:
    d = {c.name: getattr(st, c.name) for c in st.__table__.columns}
    d["tags"] = tags if tags is not None else get_tags_for(db, "storage", st.id)
    return d


def _storage_filtered_statement(
    *,
    kind: str | None,
    hardware_id: int | None,
    tag: str | None,
    q: str | None,
) -> Select[tuple[Storage]]:
    statement = select(Storage)
    if kind:
        statement = statement.where(Storage.kind == kind)
    if hardware_id:
        statement = statement.where(Storage.hardware_id == hardware_id)
    if q:
        term = f"%{escape_ilike(q)}%"
        statement = statement.where(
            or_(Storage.name.ilike(term, escape="\\"), Storage.notes.ilike(term, escape="\\"))
        )
    if tag:
        statement = (
            statement.join(
                EntityTag,
                (EntityTag.entity_type == "storage") & (EntityTag.entity_id == Storage.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    return statement


def list_storage(
    db: Session,
    *,
    kind: str | None = None,
    hardware_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = _storage_filtered_statement(kind=kind, hardware_id=hardware_id, tag=tag, q=q)
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def list_storage_page(
    db: Session,
    page: PageRequest,
    *,
    kind: str | None = None,
    hardware_id: int | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> PageResult[dict]:
    """Return a bounded storage page enriched without per-row tag queries."""
    filtered = _storage_filtered_statement(kind=kind, hardware_id=hardware_id, tag=tag, q=q)
    rows, total = paginate_rows(
        db,
        filtered=filtered,
        page=page,
        sort_columns=_STORAGE_SORT_COLUMNS,
        id_column=Storage.id,
    )
    tags = get_tags_for_many(db, "storage", [row.id for row in rows])
    items = [_to_dict(db, row, tags[row.id]) for row in rows]
    return page_result(items, total=total, page=page)


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
