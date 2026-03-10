import io
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.docs import Doc, DocCreate, DocEntityLink, DocUpdate, EntityDocAttach
from app.services import docs_service

router = APIRouter(tags=["docs"])

_DOC_UPLOADS_DIR = Path(settings.uploads_dir) / "docs"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_IMPORT_MD_BYTES = 1 * 1024 * 1024  # 1 MB per .md
_MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024  # 10 MB total ZIP

# Static routes MUST come before /{doc_id} to avoid path-matching conflicts


@router.post("/attach", status_code=201)
def attach_doc(
    payload: EntityDocAttach, db: Session = Depends(get_db), _=Depends(require_write_auth)
):
    try:
        docs_service.attach_doc(db, payload)
        return {"status": "attached"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/attach", status_code=204)
def detach_doc(
    payload: EntityDocAttach, db: Session = Depends(get_db), _=Depends(require_write_auth)
):
    try:
        docs_service.detach_doc(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


_DEFAULT_IMPORT_TITLE = "Imported Document"


def _parse_zip_entries(data: bytes) -> list[tuple[str, str]]:
    """Parse a ZIP payload and return a list of (title, body_md) tuples.

    Raises HTTPException on bad input.
    """
    if len(data) > _MAX_IMPORT_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="ZIP must be \u2264 10 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid ZIP file") from exc

    entries: list[tuple[str, str]] = []
    for info in zf.infolist():
        if info.is_dir() or not info.filename.lower().endswith(".md"):
            continue
        # Prevent path traversal \u2014 keep only the bare filename
        safe_name = Path(info.filename).name
        if not safe_name:
            continue
        md_bytes = zf.read(info)
        if len(md_bytes) > _MAX_IMPORT_MD_BYTES:
            raise HTTPException(status_code=413, detail=f"{safe_name} exceeds 1 MB limit")
        title = Path(safe_name).stem or _DEFAULT_IMPORT_TITLE
        entries.append((title, md_bytes.decode("utf-8", errors="replace")))

    if not entries:
        raise HTTPException(status_code=400, detail="No .md files found in ZIP")
    return entries


def _parse_md_entry(filename: str | None, data: bytes) -> list[tuple[str, str]]:
    """Parse a single .md payload and return a one-element (title, body_md) list.

    Raises HTTPException on bad input.
    """
    if len(data) > _MAX_IMPORT_MD_BYTES:
        raise HTTPException(status_code=413, detail=".md file must be \u2264 1 MB")
    title = Path(filename or _DEFAULT_IMPORT_TITLE).stem or _DEFAULT_IMPORT_TITLE
    return [(title, data.decode("utf-8", errors="replace"))]


@router.get("/export")
def export_docs(
    ids: list[int] | None = Query(None),
    db: Session = Depends(get_db),
):
    """Export all docs (or a filtered subset by ?ids=1&ids=2) as a ZIP of .md files."""
    data = docs_service.export_docs_zip(db, ids=ids)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="docs-export.zip"'},
    )


@router.post("/import", response_model=list[Doc], status_code=201)
async def import_docs(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Import docs from a .md file or a .zip archive containing .md files."""
    filename = (file.filename or "").lower()
    data = await file.read()

    is_zip = filename.endswith(".zip") or file.content_type in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    )
    is_md = filename.endswith(".md") or (file.content_type or "").startswith("text/")

    if is_zip:
        entries = _parse_zip_entries(data)
    elif is_md:
        entries = _parse_md_entry(file.filename, data)
    else:
        raise HTTPException(status_code=400, detail="File must be .md or .zip")

    return docs_service.import_docs(db, entries)


@router.get("/{doc_id}", response_model=Doc)
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    try:
        return docs_service.get_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{doc_id}/entities", response_model=list[DocEntityLink])
def doc_entities(doc_id: int, db: Session = Depends(get_db)):
    """Return all entity links for a doc (backlinks panel)."""
    try:
        return docs_service.entities_by_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{doc_id}", response_model=Doc)
def patch_doc(
    doc_id: int, payload: DocUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)
):
    try:
        return docs_service.update_doc(db, doc_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{doc_id}", status_code=204)
def delete_doc(doc_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        docs_service.delete_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Doc {doc_id} not found") from exc

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

    # Resolve the upload directory and verify it stays within the allowed root
    # before writing (guards against path traversal via a crafted doc_id).
    doc_root = _DOC_UPLOADS_DIR.resolve()
    doc_dir = (_DOC_UPLOADS_DIR / str(doc_id)).resolve()
    if not doc_dir.is_relative_to(doc_root):
        raise HTTPException(status_code=400, detail="Invalid document ID.")

    doc_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    # Validate filename doesn't contain path separators
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = doc_dir / filename
    # Final check that resolved file path is within the doc directory
    if not file_path.resolve().is_relative_to(doc_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid file path")
    file_path.write_bytes(data)

    url = f"/uploads/docs/{doc_id}/{filename}"
    return {"url": url}
