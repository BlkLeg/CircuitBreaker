from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsRead)
def get_settings(db: Session = Depends(get_db)):
    """Return the current app settings, initializing defaults on first access."""
    return settings_service.get_or_create_settings(db)


@router.put("", response_model=AppSettingsRead)
def put_settings(payload: AppSettingsUpdate, db: Session = Depends(get_db)):
    """Merge-update app settings. Only supplied fields are changed."""
    return settings_service.update_settings(db, payload)


@router.post("/reset", response_model=AppSettingsRead)
def reset_settings(db: Session = Depends(get_db)):
    """Reset all settings to factory defaults."""
    return settings_service.reset_settings(db)
