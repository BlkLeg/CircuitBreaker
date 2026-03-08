import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_write_auth
from app.db.session import get_db
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["assets"])

_ICON_TYPE = "image/x-icon"
_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/svg+xml", _ICON_TYPE}
_MAX_ICON_BYTES = 2 * 1024 * 1024

_UPLOADS_DIR = Path(settings.uploads_dir)
_USER_ICONS_DIR = _UPLOADS_DIR / "icons"
_BRANDING_DIR = _UPLOADS_DIR / "branding"

for directory in (_UPLOADS_DIR, _USER_ICONS_DIR, _BRANDING_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _suffix_for(content_type: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix:
        return suffix
    if content_type == "image/png":
        return ".png"
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/svg+xml":
        return ".svg"
    if content_type == _ICON_TYPE:
        return ".ico"
    return ".bin"


@router.post(
    "/user-icon", responses={400: {"description": "Invalid image format or file too large"}}
)
async def upload_user_icon(
    file: Annotated[UploadFile, File()],
    user_id: Annotated[int | None, Depends(require_write_auth)],
    db: Annotated[Session, Depends(get_db)],
):
    if file.content_type not in _ALLOWED_TYPES - {_ICON_TYPE}:
        raise HTTPException(status_code=400, detail="Invalid image format")

    content = await file.read()
    if len(content) > _MAX_ICON_BYTES:
        raise HTTPException(status_code=400, detail="File too large")

    file_hash = hashlib.sha256(content).hexdigest()
    hash_prefix = file_hash[:16]
    suffix = _suffix_for(file.content_type or "", file.filename or "")
    filename = f"user-{hash_prefix}{suffix}"
    slug = filename

    existing = db.execute(
        text("SELECT id, filename FROM user_icons WHERE hash = :hash LIMIT 1"),
        {"hash": file_hash},
    ).fetchone()
    if existing and existing[1]:
        return {
            "filename": existing[1],
            "url": f"/user-icons/{existing[1]}",
            "icon_id": existing[0],
        }

    filepath = _USER_ICONS_DIR / filename
    filepath.write_bytes(content)

    db.execute(
        text(
            """
            INSERT INTO user_icons (slug, name, category, user_id, filename, original_name, mime_type, size_bytes, hash, uploaded_at)
            VALUES (:slug, :name, :category, :user_id, :filename, :original_name, :mime_type, :size_bytes, :hash, CURRENT_TIMESTAMP)
            """
        ),
        {
            "slug": slug,
            "name": Path(file.filename or filename).stem,
            "category": "UPLOADED",
            "user_id": user_id,
            "filename": filename,
            "original_name": file.filename,
            "mime_type": file.content_type,
            "size_bytes": len(content),
            "hash": file_hash,
        },
    )
    icon_id = db.execute(
        text("SELECT id FROM user_icons WHERE hash = :hash"), {"hash": file_hash}
    ).scalar()
    db.commit()

    return {"filename": filename, "url": f"/user-icons/{filename}", "icon_id": icon_id}


@router.post(
    "/branding/favicon", responses={400: {"description": "Invalid image format or file too large"}}
)
async def upload_favicon(
    file: Annotated[UploadFile, File()],
    _: Annotated[int | None, Depends(require_write_auth)],
    db: Annotated[Session, Depends(get_db)],
):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image format")

    content = await file.read()
    if len(content) > _MAX_ICON_BYTES:
        raise HTTPException(status_code=400, detail="File too large")

    filepath = _BRANDING_DIR / "favicon.ico"
    filepath.write_bytes(content)

    get_or_create_settings(db)
    db.execute(
        text("UPDATE app_settings SET favicon_path = :path WHERE id = 1"),
        {"path": "/branding/favicon.ico"},
    )
    db.commit()

    return {"url": "/branding/favicon.ico"}
