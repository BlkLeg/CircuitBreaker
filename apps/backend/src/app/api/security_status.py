"""Security status endpoint — exposes auth configuration state for the frontend warning banner."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["security"])


class SecurityStatus(BaseModel):
    auth_enabled: bool
    has_users: bool
    warning: str | None


@router.get("/status", response_model=SecurityStatus)
def get_security_status(db: Session = Depends(get_db)):
    """Public endpoint: returns current auth state and an optional warning message.

    This endpoint is intentionally unauthenticated so the frontend can always
    display a warning when auth is disabled — even before any login flow.
    It does NOT expose any secrets or sensitive settings data.
    """
    cfg = get_or_create_settings(db)
    has_users = db.query(models.User).first() is not None

    warning = None
    if not cfg.auth_enabled:
        warning = (
            "Authentication is disabled. All API write endpoints are publicly accessible "
            "to anyone who can reach this server."
        )

    return SecurityStatus(
        auth_enabled=cfg.auth_enabled,
        has_users=has_users,
        warning=warning,
    )
