"""Branding endpoints: favicon upload, login logo upload, login BG upload,
asset deletion, dynamic manifest, Theme Park export/import."""

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import require_role
from app.core.time import utcnow
from app.core.upload_validation import SUFFIX_TO_MIME, verify_image_magic_bytes
from app.db.session import get_db
from app.schemas.settings import BrandingConfig
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["branding"])
_logger = logging.getLogger(__name__)

_BRANDING_DIR = Path(settings.uploads_dir) / "branding"
_MAX_FAVICON_BYTES = 512 * 1024  # 512 KB
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
_MAX_BG_BYTES = 5 * 1024 * 1024  # 5 MB
_FAVICON_ALLOWED = {".ico", ".png"}
_LOGO_ALLOWED = {".png", ".jpg", ".jpeg", ".svg"}
_BG_ALLOWED = {".jpg", ".jpeg", ".png"}
_MIME_PNG = "image/png"


def _build_branding(row) -> BrandingConfig:
    raw_accents = row.accent_colors
    if isinstance(raw_accents, str):
        try:
            accent_colors = json.loads(raw_accents)
        except Exception:
            accent_colors = ["#fabd2f", "#b8bb26"]
    elif raw_accents is None:
        accent_colors = ["#fabd2f", "#b8bb26"]
    else:
        accent_colors = raw_accents
    return BrandingConfig(
        app_name=row.app_name or "Circuit Breaker",
        favicon_path=row.favicon_path,
        login_logo_path=row.login_logo_path,
        login_bg_path=getattr(row, "login_bg_path", None),
        primary_color=row.primary_color or "#fe8019",
        accent_colors=accent_colors,
    )


@router.post(
    "/upload-favicon",
    response_model=BrandingConfig,
    responses={400: {"description": "Invalid favicon format or size"}},
)
async def upload_favicon(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
):
    """Upload a custom favicon (.ico or .png, max 512 KB)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _FAVICON_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Favicon must be .ico or .png, got {suffix!r}")

    data = await file.read()
    if len(data) > _MAX_FAVICON_BYTES:
        raise HTTPException(status_code=400, detail="Favicon must be ≤ 512 KB")
    mime = SUFFIX_TO_MIME.get(suffix, "image/x-icon" if suffix == ".ico" else "image/png")
    if not verify_image_magic_bytes(data, mime):
        raise HTTPException(status_code=400, detail="Favicon content does not match file type.")

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = _BRANDING_DIR / "favicon.ico"
    dest.write_bytes(data)

    row = get_or_create_settings(db)
    row.favicon_path = "/branding/favicon.ico"
    row.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return _build_branding(row)


@router.post(
    "/upload-login-logo",
    response_model=BrandingConfig,
    responses={400: {"description": "Invalid logo format or size"}},
)
async def upload_login_logo(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
):
    """Upload a custom login logo (.png/.jpg/.svg, max 2 MB)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _LOGO_ALLOWED:
        raise HTTPException(
            status_code=400, detail=f"Login logo must be .png, .jpg, or .svg, got {suffix!r}"
        )

    data = await file.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Login logo must be ≤ 2 MB")
    if suffix != ".svg":
        mime = SUFFIX_TO_MIME.get(suffix, "image/png")
        if not verify_image_magic_bytes(data, mime, allow_svg=True):
            raise HTTPException(
                status_code=400, detail="Login logo content does not match file type."
            )

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = _BRANDING_DIR / f"login-logo{suffix}"
    dest.write_bytes(data)

    row = get_or_create_settings(db)
    row.login_logo_path = f"/branding/login-logo{suffix}"
    row.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return _build_branding(row)


@router.post(
    "/upload-login-bg",
    response_model=BrandingConfig,
    responses={400: {"description": "Invalid background format or size"}},
)
async def upload_login_bg(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
):
    """Upload a custom login background (.jpg/.png, max 5 MB).

    Large images are resized to fit within 1920×1080 using Pillow.
    The result is always saved as JPEG for consistency.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _BG_ALLOWED:
        raise HTTPException(
            status_code=400, detail=f"Login background must be .jpg or .png, got {suffix!r}"
        )

    data = await file.read()
    if len(data) > _MAX_BG_BYTES:
        raise HTTPException(status_code=400, detail="Login background must be ≤ 5 MB")
    mime = SUFFIX_TO_MIME.get(suffix, "image/jpeg")
    if not verify_image_magic_bytes(data, mime):
        raise HTTPException(
            status_code=400, detail="Login background content does not match file type."
        )

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)

    # Resize large images to max 1920×1080 with Pillow
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.thumbnail((1920, 1080), Image.LANCZOS)  # type: ignore[attr-defined]
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")  # type: ignore[assignment]
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = buf.getvalue()
    except Exception:
        # If Pillow fails, save the raw upload — it's already validated by extension
        pass

    dest = _BRANDING_DIR / "login-bg.jpg"
    dest.write_bytes(data)

    row = get_or_create_settings(db)
    row.login_bg_path = "/branding/login-bg.jpg"
    row.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return _build_branding(row)


# ── Asset Deletion ────────────────────────────────────────────────────────────

_ASSET_MAP = {
    "favicon": ("favicon_path", ["favicon.ico"]),
    "login-logo": (
        "login_logo_path",
        ["login-logo.png", "login-logo.jpg", "login-logo.jpeg", "login-logo.svg"],
    ),
    "login-bg": ("login_bg_path", ["login-bg.jpg"]),
}


@router.delete(
    "/{asset_type}",
    response_model=BrandingConfig,
    responses={400: {"description": "Unknown asset type"}},
)
def delete_branding_asset(
    asset_type: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
):
    """Remove a branding asset (favicon, login-logo, or login-bg).

    Deletes the file from disk and clears the corresponding DB path.
    """
    if asset_type not in _ASSET_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown asset type: {asset_type!r}. Must be one of: {', '.join(_ASSET_MAP)}",
        )

    col_name, candidate_files = _ASSET_MAP[asset_type]

    # Delete file(s) from disk
    for fname in candidate_files:
        fpath = _BRANDING_DIR / fname
        if fpath.exists():
            fpath.unlink(missing_ok=True)

    # Clear DB column
    row = get_or_create_settings(db)
    setattr(row, col_name, None)
    row.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        _logger.exception("Failed to commit branding asset deletion for %s", asset_type)
        raise
    db.refresh(row)
    return _build_branding(row)


# ── Dynamic PWA Manifest ──────────────────────────────────────────────────────


@router.get("/manifest.json")
def dynamic_manifest(db: Annotated[Session, Depends(get_db)]):
    """Generate a PWA manifest.json reflecting current branding settings."""
    row = get_or_create_settings(db)
    app_name = row.app_name or "Circuit Breaker"
    favicon_url = row.favicon_path or "/favicon.ico"

    manifest = {
        "name": app_name,
        "short_name": app_name[:12] if len(app_name) > 12 else app_name,
        "icons": [
            {"src": favicon_url, "sizes": "any", "type": "image/x-icon"},
            {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": _MIME_PNG},
            {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": _MIME_PNG},
        ],
        "theme_color": row.primary_color or "#fe8019",
        "background_color": "#282828",
        "display": "standalone",
    }
    # If a custom favicon was uploaded, insert it as the first 192/512 entry too
    if row.favicon_path:
        manifest["icons"].insert(  # type: ignore[attr-defined]
            0, {"src": row.favicon_path, "sizes": "192x192", "type": _MIME_PNG}
        )

    return JSONResponse(content=manifest, media_type="application/manifest+json")


class ThemeParkExport(BaseModel):
    app_name: str
    primary_color: str
    accent_colors: list[str]


class ThemeParkImport(BaseModel):
    app_name: str | None = None
    primary_color: str | None = None
    accent_colors: list[str] | None = None


@router.get("/export", response_model=ThemeParkExport)
def export_theme(db: Annotated[Session, Depends(get_db)]):
    """Export branding as a Theme Park-compatible JSON blob."""
    row = get_or_create_settings(db)
    branding = _build_branding(row)
    return ThemeParkExport(
        app_name=branding.app_name,
        primary_color=branding.primary_color,
        accent_colors=branding.accent_colors,
    )


@router.post("/import", response_model=BrandingConfig)
def import_theme(
    payload: ThemeParkImport,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, require_role("admin")] = None,
):
    """Import a Theme Park JSON blob. Updates name/colors only; does NOT change file paths."""
    row = get_or_create_settings(db)
    if payload.app_name is not None:
        row.app_name = payload.app_name.strip() or row.app_name
    if payload.primary_color is not None:
        row.primary_color = payload.primary_color
    if payload.accent_colors is not None:
        row.accent_colors = json.dumps(payload.accent_colors)
    row.updated_at = utcnow()
    try:
        db.commit()
    except Exception:
        _logger.exception("Failed to commit theme import")
        raise
    db.refresh(row)
    return _build_branding(row)
