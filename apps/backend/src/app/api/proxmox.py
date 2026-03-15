"""Proxmox VE integration API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.session import get_db
from app.schemas.proxmox import (
    ProxmoxActionRequest,
    ProxmoxActionResponse,
    ProxmoxClusterOverviewResponse,
    ProxmoxConfigCreate,
    ProxmoxConfigOut,
    ProxmoxConfigUpdate,
    ProxmoxDiscoverResponse,
    ProxmoxSyncStatus,
    ProxmoxTestResponse,
)
from app.services import proxmox_service
from app.services.credential_vault import get_vault
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_FOUND = "Integration not found"
_VAULT_NOT_READY = (
    "Vault is not initialized. A vault key must be generated during OOBE setup "
    "before encrypted credentials can be stored. Go to Settings > System to complete setup."
)


def _require_vault() -> None:
    if not get_vault().is_initialized:
        raise HTTPException(status_code=503, detail=_VAULT_NOT_READY)


def _config_out(config) -> dict:
    """Convert IntegrationConfig to ProxmoxConfigOut-compatible dict."""
    import json

    extra = json.loads(config.extra_config) if config.extra_config else {}
    return {
        "id": config.id,
        "type": config.type,
        "name": config.name,
        "config_url": config.config_url,
        "cluster_name": config.cluster_name,
        "auto_sync": config.auto_sync,
        "sync_interval_s": config.sync_interval_s,
        "last_sync_at": config.last_sync_at,
        "last_sync_status": config.last_sync_status,
        "verify_ssl": extra.get("verify_ssl", False),
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.post("", response_model=ProxmoxConfigOut)
def create_proxmox_config(
    body: ProxmoxConfigCreate,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    _require_vault()
    config = proxmox_service.create_integration(
        db,
        name=body.name,
        config_url=str(body.config_url),
        api_token=body.api_token,
        auto_sync=body.auto_sync,
        sync_interval_s=body.sync_interval_s,
        verify_ssl=body.verify_ssl,
    )
    write_log(
        db,
        category="integrations",
        action="create_proxmox_integration",
        entity_type="integration_config",
        entity_id=config.id,
    )
    return _config_out(config)


@router.get("", response_model=list[ProxmoxConfigOut])
def list_proxmox_configs(db: Session = Depends(get_db), current_user=require_role("admin")):
    configs = proxmox_service.list_integrations(db)
    return [_config_out(c) for c in configs]


@router.get("/cluster-overview", response_model=ProxmoxClusterOverviewResponse)
async def get_cluster_overview(
    integration_id: int = Query(..., description="Proxmox integration ID"),
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    """Return cluster overview for dashboard: cluster info, problems, time-series, storage. Cached 90s."""
    import json

    from app.core.nats_client import nats_client

    cache_key = f"proxmox_overview.{integration_id}"

    def _make_response(payload):
        try:
            return ProxmoxClusterOverviewResponse.model_validate(payload)
        except ValidationError as e:
            _logger.warning(
                "Proxmox cluster-overview response validation failed for integration_id=%s: %s",
                integration_id,
                e,
            )
            raise HTTPException(
                status_code=500,
                detail="Cluster overview data could not be validated.",
            ) from e

    if nats_client.is_connected:
        try:
            cached_data = await nats_client.kv_get("dashboard_cache", cache_key)
            if cached_data:
                payload = json.loads(cached_data)
                _logger.debug(
                    "Proxmox cluster-overview cache hit for integration_id=%s", integration_id
                )
                return _make_response(payload)
        except (ValidationError, HTTPException):
            raise
        except Exception as exc:
            _logger.debug("Proxmox cluster-overview cache read failed: %s", exc)

    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    payload = await proxmox_service.get_cluster_overview(db, integration_id)

    if nats_client.is_connected:
        try:
            validated = _make_response(payload)
            await nats_client.kv_put(
                "dashboard_cache", cache_key, json.dumps(validated.model_dump(mode="json"))
            )
        except (ValidationError, HTTPException):
            raise
        except Exception as exc:
            _logger.debug("Proxmox cluster-overview cache write failed: %s", exc)

    return _make_response(payload)


@router.get("/{integration_id}", response_model=ProxmoxConfigOut)
def get_proxmox_config(
    integration_id: int, db: Session = Depends(get_db), current_user=require_role("admin")
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return _config_out(config)


@router.put("/{integration_id}", response_model=ProxmoxConfigOut)
def update_proxmox_config(
    integration_id: int,
    body: ProxmoxConfigUpdate,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if body.api_token is not None:
        _require_vault()
    config = proxmox_service.update_integration(
        db,
        config,
        name=body.name,
        config_url=str(body.config_url) if body.config_url is not None else None,
        api_token=body.api_token,
        auto_sync=body.auto_sync,
        sync_interval_s=body.sync_interval_s,
        verify_ssl=body.verify_ssl,
    )
    write_log(
        db,
        category="integrations",
        action="update_proxmox_integration",
        entity_type="integration_config",
        entity_id=config.id,
    )
    return _config_out(config)


@router.delete("/{integration_id}")
def delete_proxmox_config(
    integration_id: int, db: Session = Depends(get_db), current_user=require_role("admin")
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    try:
        proxmox_service.delete_integration(db, config)
    except Exception as exc:
        _logger.exception("Failed to delete Proxmox integration %d: %s", integration_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to delete integration. Please try again."
        ) from exc
    write_log(
        db,
        category="integrations",
        action="delete_proxmox_integration",
        entity_type="integration_config",
        entity_id=integration_id,
    )
    return {"ok": True}


# ── Test / Discover / Status ─────────────────────────────────────────────────


@router.post("/{integration_id}/test", response_model=ProxmoxTestResponse)
async def test_proxmox_connection(
    integration_id: int, db: Session = Depends(get_db), current_user=require_role("admin")
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    try:
        result = await proxmox_service.test_connection(db, config)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{integration_id}/discover", response_model=ProxmoxDiscoverResponse)
async def discover_proxmox_cluster(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    try:
        result = await proxmox_service.discover_and_import(db, config, queue_for_review=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    actor_name = "system"
    if current_user:
        actor_name = current_user.display_name or current_user.email

    write_log(
        db,
        category="integrations",
        action="proxmox_discover",
        entity_type="integration_config",
        entity_id=config.id,
        actor_id=current_user.id,
        actor_name=actor_name,
        details=f"nodes={result['nodes_imported']} vms={result['vms_imported']} cts={result['cts_imported']}",
    )
    return result


@router.get("/{integration_id}/status", response_model=ProxmoxSyncStatus)
def get_proxmox_status(
    integration_id: int, db: Session = Depends(get_db), current_user=require_role("admin")
):
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return proxmox_service.get_sync_status(db, config)


# ── VM/CT Actions ────────────────────────────────────────────────────────────


@router.post(
    "/{integration_id}/nodes/{node}/{vm_type}/{vmid}/action",
    response_model=ProxmoxActionResponse,
)
async def proxmox_vm_action(
    integration_id: int,
    node: str,
    vm_type: str,
    vmid: int,
    body: ProxmoxActionRequest,
    db: Session = Depends(get_db),
    current_user=require_role("admin"),
):
    if vm_type not in ("qemu", "lxc"):
        raise HTTPException(status_code=400, detail="vm_type must be 'qemu' or 'lxc'")
    config = proxmox_service.get_integration(db, integration_id)
    if not config:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    result = await proxmox_service.execute_vm_action(db, config, node, vmid, vm_type, body.action)
    write_log(
        db,
        category="integrations",
        action=f"proxmox_vm_{body.action}",
        entity_type="compute_unit",
        details=f"node={node} vm_type={vm_type} vmid={vmid}",
    )
    return result
