from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import get_limit, limiter
from app.db.session import get_db
from app.schemas.auth import (
    BootstrapInitializeRequest,
    BootstrapInitializeResponse,
    BootstrapStatusResponse,
)
from app.services import auth_service
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["bootstrap"])


@router.get("/status", response_model=BootstrapStatusResponse)
def get_bootstrap_status(db: Annotated[Session, Depends(get_db)]):
    return auth_service.bootstrap_status(db)


@router.post("/initialize", response_model=BootstrapInitializeResponse)
@limiter.limit(lambda: get_limit("auth"))
def initialize_bootstrap(
    request: Request,
    payload: BootstrapInitializeRequest,
    db: Annotated[Session, Depends(get_db)],
):
    cfg = get_or_create_settings(db)
    return auth_service.bootstrap_initialize(
        db=db,
        cfg=cfg,
        email=payload.email,
        password=payload.password,
        theme_preset=payload.theme_preset,
        display_name=payload.display_name,
        api_base_url=payload.api_base_url,
        timezone=payload.timezone,
        language=payload.language,
        ui_font=payload.ui_font,
        ui_font_size=payload.ui_font_size,
        theme=payload.theme,
        weather_location=payload.weather_location,
        smtp_enabled=payload.smtp_enabled,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password=payload.smtp_password,
        smtp_from_email=payload.smtp_from_email,
        smtp_from_name=payload.smtp_from_name,
        smtp_tls=payload.smtp_tls,
    )
