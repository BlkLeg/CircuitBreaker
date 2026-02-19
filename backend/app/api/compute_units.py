import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.compute_units import ComputeUnit, ComputeUnitCreate, ComputeUnitUpdate
from app.services import compute_units_service

router = APIRouter(prefix="/compute-units", tags=["compute-units"])

ICON_UPLOAD_DIR = Path("data/user-icons")
ICON_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_TYPES = {"image/svg+xml", "image/png", "image/jpeg", "image/webp"}
MAX_SIZE = 1 * 1024 * 1024  # 1 MB


@router.get("", response_model=list[ComputeUnit])
def list_compute_units(
    kind: str | None = Query(None),
    hardware_id: int | None = Query(None),
    environment: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return compute_units_service.list_compute_units(
        db, kind=kind, hardware_id=hardware_id, environment=environment, tag=tag, q=q
    )


@router.post("", response_model=ComputeUnit, status_code=201)
def create_compute_unit(payload: ComputeUnitCreate, db: Session = Depends(get_db)):
    return compute_units_service.create_compute_unit(db, payload)


@router.get("/{cu_id}", response_model=ComputeUnit)
def get_compute_unit(cu_id: int, db: Session = Depends(get_db)):
    try:
        return compute_units_service.get_compute_unit(db, cu_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{cu_id}", response_model=ComputeUnit)
def patch_compute_unit(cu_id: int, payload: ComputeUnitUpdate, db: Session = Depends(get_db)):
    try:
        return compute_units_service.update_compute_unit(db, cu_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{cu_id}", status_code=204)
def delete_compute_unit(cu_id: int, db: Session = Depends(get_db)):
    try:
        compute_units_service.delete_compute_unit(db, cu_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Icon upload ───────────────────────────────────────────────────────────────


@router.post("/icons/upload")
async def upload_icon(file: UploadFile = File(...)):
    """Accept an SVG/PNG icon upload. Returns the slug and public path."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}. Allowed: SVG, PNG, JPEG, WebP.")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 1 MB limit.")
    suffix = Path(file.filename).suffix or ".svg"
    slug = f"user-{uuid.uuid4().hex[:8]}{suffix}"
    dest = ICON_UPLOAD_DIR / slug
    dest.write_bytes(data)
    return {"slug": slug, "path": f"/user-icons/{slug}"}
