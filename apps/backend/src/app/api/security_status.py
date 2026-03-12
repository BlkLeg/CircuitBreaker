"""Security status endpoint — exposes auth configuration state for the frontend."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db

router = APIRouter(tags=["security"])


class SecurityStatus(BaseModel):
    auth_enabled: bool
    has_users: bool
    warning: str | None


@router.get("/status", response_model=SecurityStatus)
def get_security_status(db: Session = Depends(get_db)):
    """Public endpoint: returns current auth state.

    Authentication is always enabled once OOBE is complete.
    This endpoint is intentionally unauthenticated so the frontend
    can query auth state before login.
    """
    has_users = db.query(models.User).first() is not None

    return SecurityStatus(
        auth_enabled=True,
        has_users=has_users,
        warning=None,
    )
