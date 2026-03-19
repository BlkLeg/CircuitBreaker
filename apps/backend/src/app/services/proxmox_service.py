"""Proxmox VE integration service — discovery, import, telemetry, and actions."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.db.models import (
    ComputeUnit,
    Credential,
    Hardware,
    HardwareCluster,
    IntegrationConfig,
    Storage,
)
from app.services.credential_vault import get_vault
from app.services.proxmox_client import (
    _get_client,
    _invalidate_proxmox_client_cache,
)
from app.services.proxmox_discovery import (
    discover_and_import,  # noqa: F401
)
from app.services.proxmox_queries import (
    get_cluster_overview,  # noqa: F401
    get_proxmox_discover_run,  # noqa: F401
    get_sync_status,  # noqa: F401
    list_proxmox_discover_runs,  # noqa: F401
    test_connection,  # noqa: F401
)
from app.services.proxmox_telemetry import (
    poll_node_telemetry,  # noqa: F401
    poll_rrd_telemetry,  # noqa: F401
    poll_vm_telemetry,  # noqa: F401
    refresh_proxmox_storage,  # noqa: F401
)

_logger = logging.getLogger(__name__)


# ── Config CRUD ──────────────────────────────────────────────────────────────


def create_integration(
    db: Session,
    name: str,
    config_url: str,
    api_token: str,
    auto_sync: bool = True,
    sync_interval_s: int = 300,
    verify_ssl: bool = False,
) -> IntegrationConfig:
    vault = get_vault()
    cred = Credential(
        credential_type="proxmox_api",
        encrypted_value=vault.encrypt(api_token),
        label=f"Proxmox: {name}",
    )
    db.add(cred)
    db.flush()

    config = IntegrationConfig(
        type="proxmox",
        name=name,
        config_url=config_url.rstrip("/"),
        credential_id=cred.id,
        auto_sync=auto_sync,
        sync_interval_s=sync_interval_s,
        extra_config=json.dumps({"verify_ssl": verify_ssl}),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_integration(
    db: Session,
    config: IntegrationConfig,
    name: str | None = None,
    config_url: str | None = None,
    api_token: str | None = None,
    auto_sync: bool | None = None,
    sync_interval_s: int | None = None,
    verify_ssl: bool | None = None,
) -> IntegrationConfig:
    if name is not None:
        config.name = name
    if config_url is not None:
        config.config_url = config_url.rstrip("/")
    if auto_sync is not None:
        config.auto_sync = auto_sync
    if sync_interval_s is not None:
        config.sync_interval_s = sync_interval_s

    if api_token:
        vault = get_vault()
        cred = db.get(Credential, config.credential_id)
        if cred:
            cred.encrypted_value = vault.encrypt(api_token)
        else:
            cred = Credential(
                credential_type="proxmox_api",
                encrypted_value=vault.encrypt(api_token),
                label=f"Proxmox: {config.name}",
            )
            db.add(cred)
            db.flush()
            config.credential_id = cred.id

    if verify_ssl is not None:
        extra = json.loads(str(config.extra_config)) if config.extra_config else {}
        extra["verify_ssl"] = verify_ssl
        config.extra_config = json.dumps(extra)  # type: ignore[assignment]

    db.commit()
    db.refresh(config)
    _invalidate_proxmox_client_cache(config.id)
    return config


def delete_integration(db: Session, config: IntegrationConfig) -> None:
    _invalidate_proxmox_client_cache(config.id)
    # Nullify child FKs before deleting to prevent FK constraint violations
    for model in (Hardware, ComputeUnit, Storage, HardwareCluster):
        db.query(model).filter(model.integration_config_id == config.id).update(
            {"integration_config_id": None}, synchronize_session=False
        )
    if config.credential_id:
        cred = db.get(Credential, config.credential_id)
        if cred:
            db.delete(cred)
    db.delete(config)
    db.commit()


def get_integration(db: Session, integration_id: int) -> IntegrationConfig | None:
    return (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.id == integration_id,
            IntegrationConfig.type == "proxmox",
        )
        .first()
    )


def list_integrations(db: Session) -> list[IntegrationConfig]:
    return db.query(IntegrationConfig).filter(IntegrationConfig.type == "proxmox").all()


# ── VM Actions ───────────────────────────────────────────────────────────────


async def execute_vm_action(
    db: Session,
    config: IntegrationConfig,
    node: str,
    vmid: int,
    vm_type: str,
    action: str,
) -> dict:
    try:
        client = _get_client(db, config)
        upid = await client.vm_action(node, vmid, vm_type, action)
        return {"ok": True, "upid": str(upid)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
