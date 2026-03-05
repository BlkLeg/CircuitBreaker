
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ComputeUnit, ExternalNode, Hardware, MiscItem, Network, Service, Storage
from app.db.session import get_db

router = APIRouter(tags=["search"])


class SearchResult(BaseModel):
    id: str
    type: str
    title: str
    description: str | None = None
    action_url: str


SOURCES = [
    (Hardware, "hardware", "/hardware", "notes"),
    (ComputeUnit, "compute", "/compute-units", "notes"),
    (Service, "service", "/services", "description"),
    (Storage, "storage", "/storage", "notes"),
    (Network, "network", "/networks", "description"),
    (MiscItem, "misc", "/misc", "description"),
    (ExternalNode, "external", "/external-nodes", "notes"),
]


@router.get("", response_model=list[SearchResult])
def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    results: list[SearchResult] = []
    term = f"%{q}%"
    for Model, type_key, action_url, desc_field in SOURCES:
        rows = db.execute(select(Model).where(Model.name.ilike(term))).scalars().all()
        for row in rows:
            results.append(
                SearchResult(
                    id=f"{type_key}-{row.id}",
                    type=type_key,
                    title=row.name,
                    description=getattr(row, desc_field, None),
                    action_url=action_url,
                )
            )
    return results[:20]
