"""Branding endpoints: favicon upload, login logo upload, Theme Park export/import."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.settings import BrandingConfig
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/branding", tags=["branding"])

_BRANDING_DIR = Path(settings.uploads_dir) / "branding"
_MAX_FAVICON_BYTES = 512 * 1024   # 512 KB
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
_FAVICON_ALLOWED = {".ico", ".png"}
_LOGO_ALLOWED = {".png", ".jpg", ".jpeg", ".svg"}


def _build_branding(row) -> BrandingConfig:
    raw_accents = row.accent_colors
    if isinstance(raw_accents, str):
        try:
            accent_colors = json.loads(raw_accents)
        except Exception:
            accent_colors = ["#ff6b6b", "#4ecdc4"]
    elif raw_accents is None:
        accent_colors = ["#ff6b6b", "#4ecdc4"]
    else:
        accent_colors = raw_accents
    return BrandingConfig(
        app_name=row.app_name or "Circuit Breaker",
        favicon_path=row.favicon_path,
        login_logo_path=row.login_logo_path,
        primary_color=row.primary_color or "#00d4ff",
        accent_colors=accent_colors,
    )


@router.post("/upload-favicon", response_model=BrandingConfig)
async def upload_favicon(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Upload a custom favicon (.ico or .png, max 512 KB)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _FAVICON_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Favicon must be .ico or .png, got {suffix!r}")

    data = await file.read()
    if len(data) > _MAX_FAVICON_BYTES:
        raise HTTPException(status_code=400, detail="Favicon must be ≤ 512 KB")

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = _BRANDING_DIR / "favicon.ico"
    dest.write_bytes(data)

    row = get_or_create_settings(db)
    row.favicon_path = "/branding/favicon.ico"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _build_branding(row)


@router.post("/upload-login-logo", response_model=BrandingConfig)
async def upload_login_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Upload a custom login logo (.png/.jpg/.svg, max 2 MB)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _LOGO_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Login logo must be .png, .jpg, or .svg, got {suffix!r}")

    data = await file.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Login logo must be ≤ 2 MB")

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = _BRANDING_DIR / f"login-logo{suffix}"
    dest.write_bytes(data)

    row = get_or_create_settings(db)
    row.login_logo_path = f"/branding/login-logo{suffix}"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _build_branding(row)


class ThemeParkExport(BaseModel):
    app_name: str
    primary_color: str
    accent_colors: list[str]


class ThemeParkImport(BaseModel):
    app_name: Optional[str] = None
    primary_color: Optional[str] = None
    accent_colors: Optional[list[str]] = None


@router.get("/export", response_model=ThemeParkExport)
def export_theme(db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Import a Theme Park JSON blob. Updates name/colors only; does NOT change file paths."""
    row = get_or_create_settings(db)
    if payload.app_name is not None:
        row.app_name = payload.app_name.strip() or row.app_name
    if payload.primary_color is not None:
        row.primary_color = payload.primary_color
    if payload.accent_colors is not None:
        row.accent_colors = json.dumps(payload.accent_colors)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _build_branding(row)
