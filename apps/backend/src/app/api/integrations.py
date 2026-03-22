"""Integrations API — CRUD + test + monitor listing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.core.url_validation import reject_ssrf_url_proxmox as reject_ssrf_url
from app.db.models import Integration, IntegrationMonitor
from app.db.session import get_db
from app.integrations.registry import get_plugin, list_registry
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationMonitorRead,
    IntegrationRead,
    IntegrationUpdate,
    TestConnectionResult,
)

_logger = logging.getLogger(__name__)
router = APIRouter()

_MSG_NOT_FOUND = "Integration not found"
_MSG_UNKNOWN_TYPE = "Unknown integration type"
_MSG_VAULT_ERROR = "Vault not initialized — set CB_VAULT_KEY"


def _encrypt(plaintext: str) -> str:
    from app.services.credential_vault import get_vault

    try:
        return get_vault().encrypt(plaintext)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_MSG_VAULT_ERROR) from exc


def _monitor_count(db: Session, integration_id: int) -> int:
    return (
        db.query(func.count(IntegrationMonitor.id))
        .filter(IntegrationMonitor.integration_id == integration_id)
        .scalar()
        or 0
    )


def _to_read(integ: Integration, db: Session) -> IntegrationRead:
    return IntegrationRead(
        id=integ.id,
        type=integ.type,
        name=integ.name,
        base_url=integ.base_url,
        slug=integ.slug,
        sync_interval_s=integ.sync_interval_s,
        enabled=integ.enabled,
        last_synced_at=integ.last_synced_at,
        sync_status=integ.sync_status,
        sync_error=integ.sync_error,
        monitor_count=_monitor_count(db, integ.id),
    )


def _to_monitor_read(m: IntegrationMonitor, integration_name: str = "") -> IntegrationMonitorRead:
    return IntegrationMonitorRead(
        id=m.id,
        integration_id=m.integration_id,
        integration_name=integration_name,
        external_id=m.external_id,
        name=m.name,
        url=m.url,
        status=m.status,
        uptime_7d=m.uptime_7d,
        uptime_30d=m.uptime_30d,
        last_checked_at=m.last_checked_at,
    )


@router.get("/registry", response_model=list[dict])
def get_registry() -> list[dict]:
    """List available integration types and their config fields."""
    return list_registry()


@router.get("", response_model=list[IntegrationRead])
def list_integrations(db: Session = Depends(get_db)) -> list[IntegrationRead]:
    integrations = db.query(Integration).order_by(Integration.created_at).all()
    return [_to_read(i, db) for i in integrations]


@router.post("", response_model=IntegrationRead, status_code=201)
def create_integration(
    body: IntegrationCreate,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> IntegrationRead:
    if not get_plugin(body.type):
        raise HTTPException(status_code=400, detail=_MSG_UNKNOWN_TYPE)
    try:
        reject_ssrf_url(body.base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    encrypted_key = _encrypt(body.api_key) if body.api_key else None
    integ = Integration(
        type=body.type,
        name=body.name,
        base_url=body.base_url.rstrip("/"),
        api_key=encrypted_key,
        slug=body.slug.strip("/") if body.slug else None,
        sync_interval_s=body.sync_interval_s,
        enabled=body.enabled,
    )
    db.add(integ)
    db.commit()
    db.refresh(integ)
    return _to_read(integ, db)


@router.get("/monitors", response_model=list[IntegrationMonitorRead])
def list_all_monitors(db: Session = Depends(get_db)) -> list[IntegrationMonitorRead]:
    """All monitors across all integrations — used by StatusGroupBuilder."""
    rows = (
        db.query(IntegrationMonitor, Integration.name)
        .join(Integration, IntegrationMonitor.integration_id == Integration.id)
        .order_by(Integration.name, IntegrationMonitor.name)
        .all()
    )
    return [_to_monitor_read(m, integ_name) for m, integ_name in rows]


@router.patch("/{integration_id}", response_model=IntegrationRead)
def update_integration(
    integration_id: int,
    body: IntegrationUpdate,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> IntegrationRead:
    integ = db.get(Integration, integration_id)
    if not integ:
        raise HTTPException(status_code=404, detail=_MSG_NOT_FOUND)
    if body.name is not None:
        integ.name = body.name
    if body.base_url is not None:
        try:
            reject_ssrf_url(body.base_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        integ.base_url = body.base_url.rstrip("/")
    if body.api_key is not None:
        integ.api_key = _encrypt(body.api_key)
    if body.slug is not None:
        integ.slug = body.slug.strip("/") if body.slug else None
    if body.sync_interval_s is not None:
        integ.sync_interval_s = body.sync_interval_s
    if body.enabled is not None:
        integ.enabled = body.enabled
    db.commit()
    db.refresh(integ)
    return _to_read(integ, db)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> None:
    integ = db.get(Integration, integration_id)
    if not integ:
        raise HTTPException(status_code=404, detail=_MSG_NOT_FOUND)
    db.delete(integ)
    db.commit()


@router.post("/{integration_id}/test", response_model=TestConnectionResult)
def test_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> TestConnectionResult:
    integ = db.get(Integration, integration_id)
    if not integ:
        raise HTTPException(status_code=404, detail=_MSG_NOT_FOUND)
    plugin_cls = get_plugin(integ.type)
    if not plugin_cls:
        raise HTTPException(status_code=400, detail=_MSG_UNKNOWN_TYPE)
    config: dict = {"base_url": integ.base_url}
    if integ.slug:
        config["slug"] = integ.slug
    if integ.api_key:
        from app.services.credential_vault import get_vault

        try:
            config["api_key"] = get_vault().decrypt(integ.api_key)
        except Exception:
            raise HTTPException(status_code=500, detail=_MSG_VAULT_ERROR)
    ok, message = plugin_cls().test_connection(config)
    return TestConnectionResult(ok=ok, message=message)


@router.get("/{integration_id}/monitors", response_model=list[IntegrationMonitorRead])
def list_monitors_for_integration(
    integration_id: int,
    db: Session = Depends(get_db),
) -> list[IntegrationMonitorRead]:
    integ = db.get(Integration, integration_id)
    if not integ:
        raise HTTPException(status_code=404, detail=_MSG_NOT_FOUND)
    monitors = (
        db.query(IntegrationMonitor)
        .filter(IntegrationMonitor.integration_id == integration_id)
        .order_by(IntegrationMonitor.name)
        .all()
    )
    return [_to_monitor_read(m, integ.name) for m in monitors]
