from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Doc, EntityDoc
from app.schemas.docs import DocCreate, DocUpdate, EntityDocAttach


def _to_dict(doc: Doc) -> dict:
    return {c.name: getattr(doc, c.name) for c in doc.__table__.columns}


def list_docs(db: Session, *, q: str | None = None) -> list[dict]:
    stmt = select(Doc)
    if q:
        stmt = stmt.where(Doc.title.ilike(f"%{q}%"))
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(r) for r in rows]


def get_doc(db: Session, doc_id: int) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    return _to_dict(doc)


def create_doc(db: Session, payload: DocCreate) -> dict:
    doc = Doc(title=payload.title, body_md=payload.body_md)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_dict(doc)


def update_doc(db: Session, doc_id: int, payload: DocUpdate) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    doc.updated_at = datetime.now(timezone.utc)
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
