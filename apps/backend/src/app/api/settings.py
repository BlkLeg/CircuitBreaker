from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate, SmtpUpdate
from app.services import settings_service

router = APIRouter(tags=["settings"])


@router.get("", response_model=AppSettingsRead)
def get_settings(db: Session = Depends(get_db)):
    """Return the current app settings, initializing defaults on first access."""
    return settings_service.get_or_create_settings(db)


@router.put("", response_model=AppSettingsRead)
def put_settings(
    payload: AppSettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
):
    """Merge-update app settings. Only supplied fields are changed."""
    return settings_service.update_settings(db, payload, user_id=user_id)


@router.post("/reset", response_model=AppSettingsRead)
def reset_settings(db: Session = Depends(get_db), _=Depends(require_write_auth)):
    """Reset all settings to factory defaults."""
    return settings_service.reset_settings(db)


@router.patch("/smtp", response_model=AppSettingsRead)
def patch_smtp(
    payload: SmtpUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Update SMTP configuration fields only; auto-encrypts password."""
    return settings_service.update_settings(db, payload)  # type: ignore[arg-type]


@router.post("/smtp/test")
async def test_smtp(
    send_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Test SMTP connectivity and optionally send a test email to send_to."""
    from app.services.smtp_service import SmtpService

    cfg = settings_service.get_or_create_settings(db)
    if not cfg.smtp_host:
        return {"status": "error", "message": "SMTP host is not configured"}

    svc = SmtpService(cfg)
    if send_to:
        result = await svc.send_test_email(send_to)
    else:
        result = await svc.test_connection()

    cfg.smtp_last_test_at = datetime.utcnow().isoformat()
    cfg.smtp_last_test_status = result["status"]
    db.commit()
    return result
