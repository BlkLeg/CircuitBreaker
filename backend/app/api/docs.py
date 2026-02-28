from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.docs import Doc, DocCreate, DocUpdate, EntityDocAttach
from app.services import docs_service

import uuid
from pathlib import Path

router = APIRouter(prefix="/docs", tags=["docs"])

_DOC_UPLOADS_DIR = Path("data/uploads/docs")
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

# Static routes MUST come before /{doc_id} to avoid path-matching conflicts


@router.post("/attach", status_code=201)
def attach_doc(payload: EntityDocAttach, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        docs_service.attach_doc(db, payload)
        return {"status": "attached"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/attach", status_code=204)
def detach_doc(payload: EntityDocAttach, db: Session = Depends(get_db), _=Depends(require_write_auth)):
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
def create_doc(payload: DocCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    return docs_service.create_doc(db, payload)


@router.get("/{doc_id}", response_model=Doc)
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        return docs_service.get_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{doc_id}", response_model=Doc)
def patch_doc(doc_id: int, payload: DocUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return docs_service.update_doc(db, doc_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{doc_id}", status_code=204)
def delete_doc(doc_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        docs_service.delete_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{doc_id}/upload-image")
async def upload_doc_image(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Upload an image to embed in a doc. Returns the public URL."""
    # Verify doc exists
    try:
        docs_service.get_doc(db, doc_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Doc {doc_id} not found")

    # Validate content type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Read and validate size
    data = await file.read()
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be ≤ 5 MB")

    # Determine extension
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
    ext = ext_map.get(file.content_type, "png")

    # Save file
    doc_dir = _DOC_UPLOADS_DIR / str(doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    (doc_dir / filename).write_bytes(data)

    url = f"/uploads/docs/{doc_id}/{filename}"
    return {"url": url}

