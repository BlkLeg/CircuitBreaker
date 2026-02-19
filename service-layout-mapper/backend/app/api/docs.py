from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.docs import Doc, DocCreate, DocUpdate, EntityDocAttach
from app.services import docs_service

router = APIRouter(prefix="/docs", tags=["docs"])

# Static routes MUST come before /{doc_id} to avoid path-matching conflicts


@router.post("/attach", status_code=201)
def attach_doc(payload: EntityDocAttach, db: Session = Depends(get_db)):
    try:
        docs_service.attach_doc(db, payload)
        return {"status": "attached"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/attach", status_code=204)
def detach_doc(payload: EntityDocAttach, db: Session = Depends(get_db)):
    try:
        docs_service.detach_doc(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/by-entity", response_model=list[Doc])
def docs_by_entity(
    entity_type: str = Query(...),
    entity_id: int = Query(...),
    db: Session = Depends(get_db),
):
    return docs_service.docs_by_entity(db, entity_type, entity_id)


@router.get("", response_model=list[Doc])
def list_docs(q: str | None = Query(None), db: Session = Depends(get_db)):
    return docs_service.list_docs(db, q=q)


@router.post("", response_model=Doc, status_code=201)
def create_doc(payload: DocCreate, db: Session = Depends(get_db)):
    return docs_service.create_doc(db, payload)


@router.get("/{doc_id}", response_model=Doc)
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        return docs_service.get_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{doc_id}", response_model=Doc)
def patch_doc(doc_id: int, payload: DocUpdate, db: Session = Depends(get_db)):
    try:
        return docs_service.update_doc(db, doc_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{doc_id}", status_code=204)
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        docs_service.delete_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
