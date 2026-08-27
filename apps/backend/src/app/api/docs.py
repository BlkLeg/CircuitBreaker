import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_write_auth
from app.core.upload_validation import is_active_content_type, verify_image_magic_bytes
from app.db.session import get_db
from app.schemas.docs import Doc, DocCreate, DocEntityLink, DocUpdate, EntityDocAttach
from app.services import docs_service

router = APIRouter(tags=["docs"])

_DOC_UPLOADS_DIR = Path(settings.uploads_dir) / "docs"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
# The four import ceilings are NOT defined here, and are NOT imported by name
# either. They are the contract this endpoint shares with
# docs_service.export_docs_zip, they live at the one place both ends can see
# (the block at the top of docs_service.py), and every use below reads them
# through the module — `docs_service.MAX_IMPORT_ZIP_BYTES` — so that at runtime
# there is one object per ceiling rather than a definition and a snapshot of
# it. A `from app.services.docs_service import MAX_IMPORT_ZIP_BYTES` here would
# look identical and be a second name bound once at import time: moving the
# definition would then move the exporter and leave this importer where it was,
# which is R10 exactly.

# Static routes MUST come before /{doc_id} to avoid path-matching conflicts


@router.post("/attach", status_code=201)
def attach_doc(
    payload: EntityDocAttach, db: Session = Depends(get_db), _: Any = Depends(require_write_auth)
) -> dict[str, str]:
    try:
        docs_service.attach_doc(db, payload)
        return {"status": "attached"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/attach", status_code=204)
def detach_doc(
    payload: EntityDocAttach, db: Session = Depends(get_db), _: Any = Depends(require_write_auth)
) -> None:
    try:
        docs_service.detach_doc(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/by-entity", response_model=list[Doc])
def docs_by_entity(
    entity_type: str = Query(...),
    entity_id: int = Query(...),
    db: Session = Depends(get_db),
) -> Any:
    return docs_service.docs_by_entity(db, entity_type, entity_id)


@router.get("", response_model=list[Doc])
def list_docs(q: str | None = Query(None), db: Session = Depends(get_db)) -> Any:
    return docs_service.list_docs(db, q=q)


@router.post("", response_model=Doc, status_code=201)
def create_doc(
    payload: DocCreate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    return docs_service.create_doc(db, payload)


_DEFAULT_IMPORT_TITLE = "Imported Document"


def _mb(n: int) -> str:
    """Render a byte ceiling for a client-facing message.

    The numbers in the messages below are computed from the ceilings rather
    than written out, so that moving a ceiling cannot leave the API telling
    uploaders a limit that is no longer the one being enforced.
    """
    return f"{n / (1024 * 1024):g}"


def _parse_zip_entries(data: bytes) -> list[tuple[str, str]]:
    """Parse a ZIP payload and return a list of (title, body_md) tuples.

    Raises HTTPException on bad input.
    """
    if len(data) > docs_service.MAX_IMPORT_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"ZIP must be \u2264 {_mb(docs_service.MAX_IMPORT_ZIP_BYTES)} MB",
        )
    # Same blunt catch, same reason as the member read further down: this call
    # parses an attacker-supplied central directory, and BadZipFile is not the
    # only thing it produces. Fuzzing 4000 corruptions of each of the four
    # standard methods through this constructor alone raised
    # NotImplementedError("zip file version 12.8") — a byte in the version
    # field is enough — which the previous `except zipfile.BadZipFile` let out
    # as a 500, i.e. B41 was open here too and not only on the member read.
    # infolist() sits inside the try as well: it is a read of the directory
    # this constructor just parsed, it costs nothing to cover, and it is one
    # fewer place for the next zipfile release to raise something new from.
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid ZIP file") from exc

    if len(infos) > docs_service.MAX_IMPORT_ZIP_ENTRIES:
        raise HTTPException(
            status_code=413,
            detail=f"ZIP must contain \u2264 {docs_service.MAX_IMPORT_ZIP_ENTRIES} files",
        )

    entries: list[tuple[str, str]] = []
    total_bytes = 0
    for info in infos:
        if info.is_dir() or not info.filename.lower().endswith(".md"):
            continue
        # Prevent path traversal \u2014 keep only the bare filename
        safe_name = Path(info.filename).name
        if not safe_name:
            continue
        # Reject on the *declared* uncompressed size before spending anything on
        # the member. The 10 MB gate above bounds the compressed payload only,
        # and deflate turns 10 MB of one repeated byte into roughly 10 GB, so a
        # size check that happens after decompressing is a check that happens
        # after the damage.
        if info.file_size > docs_service.MAX_IMPORT_MD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{safe_name} exceeds {_mb(docs_service.MAX_IMPORT_MD_BYTES)} MB limit",
            )
        # Sum the declared sizes rather than the bytes actually read, so the
        # archive-wide budget is likewise decided before the spending: 500
        # members that each individually clear the 1 MB bar still add up to half
        # a gigabyte of docs.
        total_bytes += info.file_size
        if total_bytes > docs_service.MAX_IMPORT_TOTAL_MD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"ZIP contents exceed "
                    f"{_mb(docs_service.MAX_IMPORT_TOTAL_MD_BYTES)} MB uncompressed"
                ),
            )
        # Read through a bounded stream instead of zf.read(info). This is not
        # belt-and-braces on top of the file_size check above: zipfile's own
        # read() hands the decompressor a max_length of 1 GB and only *then*
        # truncates the result to file_size, so a member whose header lies small
        # over a real multi-gigabyte deflate stream returns the handful of bytes
        # it claimed while having materialized the whole stream on the way. A
        # sized read caps what the decompressor is allowed to produce per chunk,
        # which is the part that actually costs memory. One byte past the cap
        # distinguishes "exactly at the limit" from "over it".
        # The try around ZipFile() above covers the *central directory* only.
        # Everything a member can be wrong about surfaces here instead, and it
        # reached the client as a 500 until B41. Every one of those failures
        # means "the archive you uploaded is not readable", which is a 400 —
        # the same answer the same archive already got when its directory was
        # the broken part.
        #
        # The catch is deliberately `Exception` and must not be narrowed back
        # to a tuple. B41's first fix enumerated the five shapes a corrupt
        # *deflate or stored* member produces (zlib.error, BadZipFile for a bad
        # CRC or a clobbered local header, RuntimeError for the encrypted bit,
        # NotImplementedError for an unknown method) and a bzip2 member walked
        # straight through it: bz2's decompressor raises a bare
        # OSError("Invalid data stream"), and the two bytes that select method
        # 12 are the uploader's to set. Fuzzing 4000 corruptions of each of the
        # four methods CPython can decompress produced seven distinct types —
        # BadZipFile, zlib.error, lzma.LZMAError, OSError, ValueError
        # ("negative seek value", from a corrupted offset), RuntimeError and
        # NotImplementedError — across three modules that are free to add an
        # eighth in any CPython release. An enumeration of somebody else's
        # exception surface is a list that is wrong the moment it is written.
        #
        # What makes the blunt catch safe is the size of the try body: exactly
        # two calls, both into zipfile, on bytes the uploader controls. Do not
        # grow it. In particular the `len(md_bytes)` gate below must stay
        # outside, because HTTPException is an Exception too and moving it in
        # would turn the B05 bomb ceilings into "could not read" 400s.
        try:
            with zf.open(info) as fh:
                md_bytes = fh.read(docs_service.MAX_IMPORT_MD_BYTES + 1)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not read {safe_name} from the ZIP"
            ) from exc
        if len(md_bytes) > docs_service.MAX_IMPORT_MD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{safe_name} exceeds {_mb(docs_service.MAX_IMPORT_MD_BYTES)} MB limit",
            )
        title = Path(safe_name).stem or _DEFAULT_IMPORT_TITLE
        entries.append((title, md_bytes.decode("utf-8", errors="replace")))

    if not entries:
        raise HTTPException(status_code=400, detail="No .md files found in ZIP")
    return entries


def _parse_md_entry(filename: str | None, data: bytes) -> list[tuple[str, str]]:
    """Parse a single .md payload and return a one-element (title, body_md) list.

    Raises HTTPException on bad input.
    """
    if len(data) > docs_service.MAX_IMPORT_MD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f".md file must be \u2264 {_mb(docs_service.MAX_IMPORT_MD_BYTES)} MB",
        )
    title = Path(filename or _DEFAULT_IMPORT_TITLE).stem or _DEFAULT_IMPORT_TITLE
    return [(title, data.decode("utf-8", errors="replace"))]


@router.get("/export")
def export_docs(
    ids: list[int] | None = Query(None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export all docs (or a filtered subset by ?ids=1&ids=2) as a ZIP of .md files."""
    # No size refusal here, deliberately: an archive too big for this API's own
    # importer is still handed over, carrying a member that says so. The reason
    # a refusal is the wrong answer — the shipped caller cannot read a 413's
    # detail and has no subset-export UI to act on it — is written out on
    # export_docs_zip.
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
    _: Any = Depends(require_write_auth),
) -> Any:
    """Import docs from a .md file or a .zip archive containing .md files."""
    filename = (file.filename or "").lower()
    # Bounded read, not a bare file.read(). Every ceiling below is enforced
    # against len(data), and a ceiling checked after an unbounded read is a
    # ceiling checked after the cost it exists to prevent: Starlette spools a
    # large body to disk rather than holding it in RAM, but .read() with no
    # argument pulls all of it back into a single bytes object regardless of
    # how big it got. nginx's client_max_body_size stops this in the shipped
    # container and stops nothing for anything reaching the ASGI app directly,
    # so the bound belongs here. One byte past the cap so the len() gate can
    # still tell an upload sitting exactly on the limit from one over it. The
    # .md branch has a tighter cap of its own and applies it to this same
    # buffer, so reading to the larger of the two bounds is correct for both.
    data = await file.read(docs_service.MAX_IMPORT_ZIP_BYTES + 1)

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
def get_doc(doc_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return docs_service.get_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{doc_id}/entities", response_model=list[DocEntityLink])
def doc_entities(doc_id: int, db: Session = Depends(get_db)) -> Any:
    """Return all entity links for a doc (backlinks panel)."""
    try:
        return docs_service.entities_by_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{doc_id}", response_model=Doc)
def patch_doc(
    doc_id: int,
    payload: DocUpdate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> Any:
    try:
        return docs_service.update_doc(db, doc_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{doc_id}", status_code=204)
def delete_doc(
    doc_id: int, db: Session = Depends(get_db), _: Any = Depends(require_write_auth)
) -> None:
    try:
        docs_service.delete_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{doc_id}/upload-image")
async def upload_doc_image(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> dict[str, str]:
    """Upload an image to embed in a doc. Returns the public URL."""
    # Verify doc exists
    try:
        docs_service.get_doc(db, doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Doc {doc_id} not found") from exc

    # Validate content type
    if is_active_content_type(file.content_type, file.filename):
        raise HTTPException(status_code=400, detail="SVG and active markup uploads are not allowed")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Read and validate size. Bounded for the reason spelled out in
    # import_docs above: the 5 MB gate on the next line only bounds what this
    # handler keeps, not what an unparameterized .read() already allocated.
    data = await file.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Image must be \u2264 {_mb(_MAX_IMAGE_BYTES)} MB"
        )
    if not verify_image_magic_bytes(data, file.content_type):
        raise HTTPException(status_code=400, detail="Image content does not match declared type.")

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
