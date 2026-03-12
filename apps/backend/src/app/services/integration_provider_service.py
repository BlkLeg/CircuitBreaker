"""Service layer for unified integration provider CRUD.

Wraps existing ``IntegrationConfig`` + ``Credential`` models and
``CredentialVault`` to provide a single-entry-point for managing
integration configurations across all provider types (proxmox, docker,
truenas, unifi, etc.).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.db.models import Credential, IntegrationConfig
from app.schemas.integration_provider import (
    IntegrationProviderCreate,
    IntegrationProviderUpdate,
)
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)


def list_configs(db: Session, provider: str) -> list[IntegrationConfig]:
    return (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.type == provider)
        .order_by(IntegrationConfig.id)
        .all()
    )


def get_config(db: Session, provider: str, config_id: int) -> IntegrationConfig | None:
    cfg = db.get(IntegrationConfig, config_id)
    if cfg and cfg.type != provider:
        return None
    return cfg


def create_config(db: Session, provider: str, data: IntegrationProviderCreate) -> IntegrationConfig:
    vault = get_vault()
    credential_id: int | None = None

    if data.credential_value:
        encrypted = vault.encrypt(data.credential_value)
        cred = Credential(
            credential_type=data.credential_type,
            encrypted_value=encrypted,
            label=f"{provider}:{data.name}",
        )
        db.add(cred)
        db.flush()
        credential_id = cred.id

    cfg = IntegrationConfig(
        type=provider,
        name=data.name,
        config_url=data.config_url,
        credential_id=credential_id,
        auto_sync=data.auto_sync,
        sync_interval_s=data.sync_interval_s,
        extra_config=data.extra_config,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def update_config(
    db: Session, provider: str, config_id: int, data: IntegrationProviderUpdate
) -> IntegrationConfig | None:
    cfg = get_config(db, provider, config_id)
    if cfg is None:
        return None

    vault = get_vault()

    if data.name is not None:
        cfg.name = data.name
    if data.config_url is not None:
        cfg.config_url = data.config_url
    if data.auto_sync is not None:
        cfg.auto_sync = data.auto_sync
    if data.sync_interval_s is not None:
        cfg.sync_interval_s = data.sync_interval_s
    if data.extra_config is not None:
        cfg.extra_config = data.extra_config

    if data.credential_value is not None:
        encrypted = vault.encrypt(data.credential_value)
        if cfg.credential_id:
            cred = db.get(Credential, cfg.credential_id)
            if cred:
                cred.encrypted_value = encrypted
            else:
                new_cred = Credential(
                    credential_type="api_key",
                    encrypted_value=encrypted,
                    label=f"{provider}:{cfg.name}",
                )
                db.add(new_cred)
                db.flush()
                cfg.credential_id = new_cred.id
        else:
            new_cred = Credential(
                credential_type="api_key",
                encrypted_value=encrypted,
                label=f"{provider}:{cfg.name}",
            )
            db.add(new_cred)
            db.flush()
            cfg.credential_id = new_cred.id

    db.commit()
    db.refresh(cfg)
    return cfg


def delete_config(db: Session, provider: str, config_id: int) -> bool:
    cfg = get_config(db, provider, config_id)
    if cfg is None:
        return False

    # Nullify child FKs before deleting to prevent FK constraint violations
    from app.db.models import ComputeUnit, Hardware, HardwareCluster, Storage

    for model in (Hardware, ComputeUnit, Storage, HardwareCluster):
        db.query(model).filter(model.integration_config_id == cfg.id).update(
            {"integration_config_id": None}, synchronize_session=False
        )

    cred_id = cfg.credential_id
    db.delete(cfg)
    if cred_id:
        cred = db.get(Credential, cred_id)
        if cred:
            db.delete(cred)
    db.commit()
    return True


async def test_config(db: Session, provider: str, config_id: int) -> dict:
    """Validate connectivity for an integration config without starting a sync.

    Dispatches to the appropriate provider-specific test function and returns
    a sanitised result that never leaks credentials.
    """
    cfg = get_config(db, provider, config_id)
    if cfg is None:
        return {"status": "error", "message": "Integration config not found", "latency_ms": 0}

    t0 = time.monotonic()
    try:
        if provider == "proxmox":
            result = await _test_proxmox(db, cfg)
        elif provider == "docker":
            result = _test_docker(cfg)
        else:
            result = {
                "status": "error",
                "message": f"Test not implemented for provider '{provider}'",
            }
    except Exception as exc:
        _logger.warning("Integration test failed for %s config %d: %s", provider, config_id, exc)
        result = {"status": "error", "message": str(exc)}

    latency_ms = round((time.monotonic() - t0) * 1000)
    result["latency_ms"] = latency_ms
    return result


async def _test_proxmox(db: Session, cfg: IntegrationConfig) -> dict:
    from app.services.proxmox_service import test_connection

    result = await test_connection(db, cfg)
    if result.get("ok"):
        return {
            "status": "ok",
            "message": f"Connected to Proxmox (version {result.get('version', 'unknown')})",
        }
    return {"status": "error", "message": result.get("error", "Connection failed")}


def _test_docker(cfg: IntegrationConfig) -> dict:
    """Test Docker daemon reachability via socket or TCP URL."""
    import docker as dockerlib

    url = cfg.config_url or "unix:///var/run/docker.sock"
    if url.startswith("/"):
        url = f"unix://{url}"

    try:
        client = dockerlib.DockerClient(base_url=url, timeout=10)
        info = client.info()
        server_version = info.get("ServerVersion", "unknown")
        containers = info.get("Containers", 0)
        client.close()
        return {
            "status": "ok",
            "message": f"Docker {server_version} ({containers} containers)",
        }
    except dockerlib.errors.DockerException as exc:
        return {"status": "error", "message": str(exc)}
