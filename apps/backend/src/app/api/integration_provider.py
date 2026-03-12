"""Unified integration provider CRUD endpoints.

Routes:
  GET    /api/v1/integrations/{provider}/config
  POST   /api/v1/integrations/{provider}/config
  GET    /api/v1/integrations/{provider}/config/{id}
  PUT    /api/v1/integrations/{provider}/config/{id}
  DELETE /api/v1/integrations/{provider}/config/{id}
  POST   /api/v1/integrations/{provider}/config/{id}/test
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rbac import require_role
from app.db.models import User
from app.db.session import get_db
from app.schemas.integration_provider import (
    VALID_PROVIDERS,
    IntegrationProviderCreate,
    IntegrationProviderRead,
    IntegrationProviderUpdate,
)
from app.services import integration_provider_service as svc

router = APIRouter(tags=["integrations"])


def _validate_provider(provider: str) -> str:
    if provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{provider}'. Must be one of: {sorted(VALID_PROVIDERS)}",
        )
    return provider


@router.get("/{provider}/config", response_model=list[IntegrationProviderRead])
def list_configs(provider: str, db: Session = Depends(get_db)):
    _validate_provider(provider)
    return svc.list_configs(db, provider)


@router.post("/{provider}/config", response_model=IntegrationProviderRead)
def create_config(
    provider: str,
    body: IntegrationProviderCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    _validate_provider(provider)
    cfg = svc.create_config(db, provider, body)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="integration_config_created",
        resource=f"integration:{provider}:{cfg.id}",
        status="ok",
    )
    return cfg


@router.get("/{provider}/config/{config_id}", response_model=IntegrationProviderRead)
def get_config(provider: str, config_id: int, db: Session = Depends(get_db)):
    _validate_provider(provider)
    cfg = svc.get_config(db, provider, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Integration config not found")
    return cfg


@router.put("/{provider}/config/{config_id}", response_model=IntegrationProviderRead)
def update_config(
    provider: str,
    config_id: int,
    body: IntegrationProviderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    _validate_provider(provider)
    cfg = svc.update_config(db, provider, config_id, body)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Integration config not found")
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="integration_config_updated",
        resource=f"integration:{provider}:{config_id}",
        status="ok",
    )
    return cfg


@router.delete("/{provider}/config/{config_id}")
def delete_config(
    provider: str,
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    _validate_provider(provider)
    if not svc.delete_config(db, provider, config_id):
        raise HTTPException(status_code=404, detail="Integration config not found")
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="integration_config_deleted",
        resource=f"integration:{provider}:{config_id}",
        status="ok",
    )
    return {"detail": "deleted"}


@router.post("/{provider}/config/{config_id}/test")
async def test_config(
    provider: str,
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = require_role("admin"),
):
    """Validate connectivity for an integration without starting a full sync.

    Returns ``{"status": "ok"|"error", "message": "...", "latency_ms": N}``.
    Credentials are never included in the response.
    """
    _validate_provider(provider)
    result = await svc.test_config(db, provider, config_id)
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="integration_config_tested",
        resource=f"integration:{provider}:{config_id}",
        status=result.get("status", "unknown"),
    )
    return result
