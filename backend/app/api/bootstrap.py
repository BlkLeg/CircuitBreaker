from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.schemas.auth import (
    BootstrapInitializeRequest,
    BootstrapInitializeResponse,
    BootstrapStatusResponse,
)
from app.services import auth_service
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])


@router.get("/status", response_model=BootstrapStatusResponse)
def get_bootstrap_status(db: Session = Depends(get_db)):
    return auth_service.bootstrap_status(db)


@router.post("/initialize", response_model=BootstrapInitializeResponse)
@limiter.limit("5/minute")
def initialize_bootstrap(
    request: Request,
    payload: BootstrapInitializeRequest,
    db: Session = Depends(get_db),
):
    cfg = get_or_create_settings(db)
    return auth_service.bootstrap_initialize(
        db,
        cfg,
        payload.email,
        payload.password,
        payload.theme_preset,
        payload.display_name,
    )
