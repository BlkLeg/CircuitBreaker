from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.models import Tag
from app.db.session import get_db
from app.schemas.tag import TagRead, TagUpdate

router = APIRouter(tags=["tags"])


@router.get("", response_model=list[TagRead])
def list_tags(db: Session = Depends(get_db)):
    """List all tags (id, name, color) for dropdowns and colored display."""
    rows = db.execute(select(Tag).order_by(Tag.name)).scalars().all()
    return [TagRead.model_validate(t) for t in rows]


@router.patch("/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    payload: TagUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Update a tag (e.g. color)."""
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if payload.color is not None:
        tag.color = payload.color
    db.commit()
    db.refresh(tag)
    return TagRead.model_validate(tag)
