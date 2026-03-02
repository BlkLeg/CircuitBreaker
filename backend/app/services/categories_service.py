from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.db.models import Category, Service


class CategoryInUseError(Exception):
    def __init__(self, services: list[dict]):
        self.services = services


def list_categories(db: Session) -> list[dict]:
    rows = (
        db.query(Category, func.count(Service.id).label("service_count"))
        .outerjoin(Service, Service.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
        .all()
    )
    result = []
    for cat, count in rows:
        result.append({
            "id": cat.id,
            "name": cat.name,
            "color": cat.color,
            "created_at": cat.created_at,
            "service_count": count,
        })
    return result


def create_category(db: Session, name: str, color: str | None = None) -> Category:
    existing = db.query(Category).filter(Category.name.ilike(name)).first()
    if existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail={"error": "Category already exists"})
    cat = Category(
        name=name,
        color=color,
        created_at=utcnow_iso(),
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def update_category(
    db: Session, category_id: int, name: str | None = None, color: str | None = None
) -> Category:
    cat = db.get(Category, category_id)
    if cat is None:
        raise ValueError(f"Category {category_id} not found")
    if name is not None:
        cat.name = name
    if color is not None:
        cat.color = color
    db.commit()
    db.refresh(cat)
    return cat


def delete_category(db: Session, category_id: int) -> None:
    cat = db.get(Category, category_id)
    if cat is None:
        raise ValueError(f"Category {category_id} not found")
    blocking = (
        db.query(Service)
        .filter(Service.category_id == category_id)
        .all()
    )
    if blocking:
        raise CategoryInUseError([{"id": s.id, "name": s.name} for s in blocking])
    db.delete(cat)
    db.commit()
