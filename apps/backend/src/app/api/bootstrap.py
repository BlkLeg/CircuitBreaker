from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.auth_cookie import auth_response_with_cookie
from app.core.rate_limit import get_limit, limiter
from app.db.session import get_db
from app.schemas.auth import (
    BootstrapInitializeOAuthRequest,
    BootstrapInitializeRequest,
    BootstrapInitializeResponse,
    BootstrapStatusResponse,
    OnboardingStepResponse,
    OnboardingStepUpdateRequest,
)
from app.services import auth_service
from app.services.settings_service import get_or_create_settings

router = APIRouter(tags=["bootstrap"])


@router.get("/status", response_model=BootstrapStatusResponse)
def get_bootstrap_status(db: Annotated[Session, Depends(get_db)]) -> BootstrapStatusResponse:
    return auth_service.bootstrap_status(db)


@router.get("/onboarding", response_model=OnboardingStepResponse)
def get_onboarding_step(db: Annotated[Session, Depends(get_db)]) -> OnboardingStepResponse:
    """Return current OOBE step (public, no auth). Used for resume and Back to start."""
    return auth_service.get_onboarding_or_fallback(db)


@router.patch("/onboarding", response_model=OnboardingStepResponse)
def set_onboarding_step(
    payload: OnboardingStepUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> OnboardingStepResponse:
    """Set OOBE step (public, no auth). Used when advancing or going Back to start."""
    return auth_service.set_onboarding_step(db, payload.step)


@router.post("/initialize", response_model=BootstrapInitializeResponse)
@limiter.limit(lambda: get_limit("auth"))
def initialize_bootstrap(
    request: Request,
    response: Response,
    payload: BootstrapInitializeRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    cfg = get_or_create_settings(db)
    password_or_hash: str = (
        payload.password_hash if payload.password_hash is not None else payload.password
    ) or ""
    result = auth_service.bootstrap_initialize(
        db=db,
        cfg=cfg,
        email=payload.email,
        password_or_hash=password_or_hash,
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
    body = result.model_dump()
    return auth_response_with_cookie(request, result.token, body, cfg.session_timeout_hours)


@router.post("/initialize-oauth", response_model=BootstrapInitializeResponse)
@limiter.limit(lambda: get_limit("auth"))
def initialize_bootstrap_oauth(
    request: Request,
    response: Response,
    payload: BootstrapInitializeOAuthRequest,
    db: Annotated[Session, Depends(get_db)],
) -> BootstrapInitializeResponse:
    cfg = get_or_create_settings(db)
    return auth_service.bootstrap_initialize_oauth(db=db, cfg=cfg, payload=payload)
