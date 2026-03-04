import io
import re
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.markdown_render import render_markdown
from app.core.time import utcnow
from app.db.models import Doc, EntityDoc
from app.schemas.docs import DocCreate, DocUpdate, EntityDocAttach

_MAX_IMPORT_MD_BYTES = 1 * 1024 * 1024    # 1 MB per .md entry
_MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024  # 10 MB total ZIP


def _slugify(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") or "doc"


def _to_dict(doc: Doc) -> dict:
    return {c.name: getattr(doc, c.name) for c in doc.__table__.columns}


def list_docs(db: Session, *, q: str | None = None) -> list[dict]:
    stmt = select(Doc)
    if q:
        stmt = stmt.where(Doc.title.ilike(f"%{q}%"))
    # Pinned docs always float to the top; within each group sort by recency
    stmt = stmt.order_by(Doc.pinned.desc(), Doc.updated_at.desc())
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(r) for r in rows]


def get_doc(db: Session, doc_id: int) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    return _to_dict(doc)


def create_doc(db: Session, payload: DocCreate) -> dict:
    doc = Doc(
        title=payload.title,
        body_md=payload.body_md,
        body_html=render_markdown(payload.body_md),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_dict(doc)


def update_doc(db: Session, doc_id: int, payload: DocUpdate) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(doc, field, value)
    # Re-render HTML when body changes
    if "body_md" in data:
        doc.body_html = render_markdown(doc.body_md)
    doc.updated_at = utcnow()
    db.commit()
    db.refresh(doc)
    return _to_dict(doc)


def delete_doc(db: Session, doc_id: int) -> None:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    db.delete(doc)
    db.commit()


def attach_doc(db: Session, payload: EntityDocAttach) -> None:
    if db.get(Doc, payload.doc_id) is None:
        raise ValueError(f"Doc {payload.doc_id} not found")
    link = EntityDoc(entity_type=payload.entity_type, entity_id=payload.entity_id, doc_id=payload.doc_id)
    db.add(link)
    db.commit()


def detach_doc(db: Session, payload: EntityDocAttach) -> None:
    link = db.execute(
        select(EntityDoc).where(
            EntityDoc.entity_type == payload.entity_type,
            EntityDoc.entity_id == payload.entity_id,
            EntityDoc.doc_id == payload.doc_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise ValueError("Doc attachment not found")
    db.delete(link)
    db.commit()


def docs_by_entity(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    links = db.execute(
        select(EntityDoc).where(
            EntityDoc.entity_type == entity_type,
            EntityDoc.entity_id == entity_id,
        )
    ).scalars().all()
    result = []
    for link in links:
        doc = db.get(Doc, link.doc_id)
        if doc:
            result.append(_to_dict(doc))
    return result


def export_docs_zip(db: Session, ids: list[int] | None = None) -> bytes:
    """Return an in-memory ZIP archive containing one .md file per doc."""
    stmt = select(Doc)
    if ids:
        stmt = stmt.where(Doc.id.in_(ids))
    docs = db.execute(stmt).scalars().all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            filename = f"{doc.id}-{_slugify(doc.title)}.md"
            zf.writestr(filename, doc.body_md)
    return buf.getvalue()


def import_docs(db: Session, entries: list[tuple[str, str]]) -> list[dict]:
    """Create docs from a list of (title, body_md) tuples; returns the created doc dicts."""
    created = []
    for title, body_md in entries:
        doc = create_doc(db, DocCreate(title=title, body_md=body_md))
        created.append(doc)
    return created


def entities_by_doc(db: Session, doc_id: int) -> list[dict]:
    """Return all entity links for a given doc (reverse lookup for backlinks panel)."""
    if db.get(Doc, doc_id) is None:
        raise ValueError(f"Doc {doc_id} not found")
    links = db.execute(
        select(EntityDoc).where(EntityDoc.doc_id == doc_id)
    ).scalars().all()
    return [
        {"entity_type": link.entity_type, "entity_id": link.entity_id}
        for link in links
    ]
