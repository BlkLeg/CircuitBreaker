from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.categories import CategoryCreate, CategoryRead, CategoryUpdate
from app.services.categories_service import (
    CategoryInUseError,
    create_category,
    delete_category,
    list_categories,
    update_category,
)

router = APIRouter(tags=["categories"])


@router.get("", response_model=list[CategoryRead])
def get_categories(db: Session = Depends(get_db)):
    return list_categories(db)


@router.post("", response_model=CategoryRead, status_code=201)
def post_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    try:
        cat = create_category(db, payload.name, payload.color)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    count = list_categories(db)
    for c in count:
        if c["id"] == cat.id:
            return c
    return {
        "id": cat.id,
        "name": cat.name,
        "color": cat.color,
        "created_at": cat.created_at,
        "service_count": 0,
    }


@router.patch("/{category_id}", response_model=CategoryRead)
def patch_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    try:
        update_category(db, category_id, payload.name, payload.color)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Category not found") from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    rows = list_categories(db)
    for c in rows:
        if c["id"] == category_id:
            return c
    raise HTTPException(status_code=404, detail="Category not found")


@router.delete("/{category_id}", status_code=204)
def del_category(category_id: int, db: Session = Depends(get_db)):
    try:
        delete_category(db, category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Category not found") from exc
    except CategoryInUseError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "Category is in use", "blocking_services": e.services},
        ) from e
