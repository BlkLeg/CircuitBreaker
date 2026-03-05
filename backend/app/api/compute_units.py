import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_write_auth
from app.db.models import ComputeNetwork, UserIcon
from app.db.session import get_db
from app.schemas.compute_units import ComputeUnit, ComputeUnitCreate, ComputeUnitUpdate
from app.schemas.networks import ComputeNetworkRead
from app.services import compute_units_service

router = APIRouter(tags=["compute-units"])

router = APIRouter(tags=["compute-units"])

ICON_UPLOAD_DIR = Path(settings.uploads_dir) / "icons"
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE = 1 * 1024 * 1024  # 1 MB

# Allowlist for icon slugs: alphanumeric, hyphens, underscores, dots only.
_SAFE_SLUG_RE = re.compile(r'^[a-zA-Z0-9_\-\.]+$')


@router.get("", response_model=list[ComputeUnit])
def list_compute_units(
    kind: str | None = Query(None),
    hardware_id: int | None = Query(None),
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return compute_units_service.list_compute_units(
        db, kind=kind, hardware_id=hardware_id, environment=environment,
        environment_id=environment_id, tag=tag, q=q
    )


@router.post("", response_model=ComputeUnit, status_code=201)
def create_compute_unit(payload: ComputeUnitCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return compute_units_service.create_compute_unit(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


# ── Icon endpoints ───────────────────────────────────────────────────────────
# Must be registered BEFORE /{cu_id} to avoid FastAPI matching "icons" as an int.

@router.get("/icons")
def list_icons(db: Session = Depends(get_db)):
    """Return all previously-uploaded user icons as [{slug, path, label, category}]."""
    icons = []
    
    # Let's map from db
    db_icons = {icon.slug: icon for icon in db.query(UserIcon).all()}

    if ICON_UPLOAD_DIR.exists():
        for f in sorted(ICON_UPLOAD_DIR.iterdir()):
            if f.is_file():
                slug = f.name
                label = f.stem
                category = "UPLOADED"
                
                if slug in db_icons:
                    if db_icons[slug].name:
                        label = db_icons[slug].name
                    if db_icons[slug].category:
                        category = db_icons[slug].category

                icons.append({
                    "slug": slug,
                    "path": f"/user-icons/{slug}",
                    "label": label,
                    "category": category
                })
    return icons


# Magic-byte signatures used to verify actual file content matches declared MIME type.
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png":  [b"\x89PNG"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP — checked in body below
}


def _verify_magic_bytes(data: bytes, content_type: str) -> bool:
    """Return True when the file's leading bytes match the declared MIME type."""
    signatures = _MAGIC_BYTES.get(content_type)
    if signatures is None:
        return False
    if not signatures:  # SVG — skip binary magic-byte check
        return True
    for sig in signatures:
        if data[:len(sig)] == sig:
            # Extra WebP check: bytes 8-12 must read "WEBP"
            if content_type == "image/webp" and data[8:12] != b"WEBP":
                return False
            return True
    return False


@router.post("/icons/upload")
async def upload_icon(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    category: str | None = Form(None),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth)
):
    """Accept a PNG/JPEG/WebP icon upload with metadata. SVG is blocked due to XSS risk."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}. Allowed: PNG, JPEG, WebP.")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 1 MB limit.")
    # Server-side magic-byte validation: reject uploads where content does not
    # match the client-declared MIME type (prevents content-type spoofing).
    if not _verify_magic_bytes(data, file.content_type):
        raise HTTPException(status_code=415, detail="File content does not match the declared content type.")
    
    # Ensure directory exists before saving (fix for brand-new instances handling first uploads)
    ICON_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    suffix = Path(file.filename).suffix or ".png"
    slug = f"user-{uuid.uuid4().hex[:8]}{suffix}"
    dest = ICON_UPLOAD_DIR / slug
    dest.write_bytes(data)
    
    db_icon = UserIcon(slug=slug, name=name, category=category)
    db.add(db_icon)
    db.commit()
    
    return {
        "slug": slug,
        "path": f"/user-icons/{slug}",
        "label": name or dest.stem,
        "category": category or "UPLOADED"
    }


@router.delete("/icons/{slug}", status_code=204)
def delete_icon(slug: str, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    """Delete a previously-uploaded user icon by slug."""
    if not slug.startswith("user-"):
        raise HTTPException(status_code=400, detail="Only user-uploaded icons can be deleted.")
    # Reject slugs that contain characters outside the safe allowlist before any
    # path construction to satisfy static analysis and prevent path traversal.
    if not _SAFE_SLUG_RE.match(slug) or '..' in slug:
        raise HTTPException(status_code=400, detail="Invalid icon slug.")
    # Canonicalise and verify the resolved path remains within ICON_UPLOAD_DIR.
    icon_root = ICON_UPLOAD_DIR.resolve()
    dest = (ICON_UPLOAD_DIR / slug).resolve()
    if not dest.is_relative_to(icon_root):
        raise HTTPException(status_code=400, detail="Invalid icon slug.")
    dest.unlink(missing_ok=True)
    
    db_icon = db.query(UserIcon).filter((UserIcon.slug == slug) | (UserIcon.filename == slug)).first()
    if db_icon:
        db.delete(db_icon)
        db.commit()
        
    return JSONResponse(status_code=204, content=None)


@router.get("/{cu_id}/networks", response_model=list[ComputeNetworkRead])
def list_compute_networks(cu_id: int, db: Session = Depends(get_db)):
    """Return all network memberships for a compute unit."""
    rows = db.execute(
        select(ComputeNetwork).where(ComputeNetwork.compute_id == cu_id)
    ).scalars().all()
    return list(rows)


@router.get("/{cu_id}", response_model=ComputeUnit)
def get_compute_unit(cu_id: int, db: Session = Depends(get_db)):
    try:
        return compute_units_service.get_compute_unit(db, cu_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{cu_id}", response_model=ComputeUnit)
def patch_compute_unit(cu_id: int, payload: ComputeUnitUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return compute_units_service.update_compute_unit(db, cu_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{cu_id}", status_code=204)
def delete_compute_unit(cu_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        compute_units_service.delete_compute_unit(db, cu_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Cannot delete: other records still reference this compute unit.")
