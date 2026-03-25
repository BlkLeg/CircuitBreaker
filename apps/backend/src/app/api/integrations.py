"""Integrations API — CRUD + test + monitor listing."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.core.url_validation import reject_ssrf_url_proxmox as reject_ssrf_url
from app.db.models import (
    Integration,
    IntegrationMonitor,
    IntegrationMonitorEvent,
    StatusGroup,
    StatusPage,
)
from app.db.session import get_db
from app.integrations.registry import get_plugin, list_registry
from app.schemas.integration import (
    EventAnnotate,
    IntegrationCreate,
    IntegrationMonitorEventRead,
    IntegrationMonitorRead,
    IntegrationRead,
    IntegrationUpdate,
    MonitorLinkUpdate,
    NativeMonitorCreate,
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
        base_url=integ.base_url or "",
        slug=integ.slug,
        sync_interval_s=integ.sync_interval_s,
        enabled=integ.enabled,
        last_synced_at=integ.last_synced_at,
        sync_status=integ.sync_status,
        sync_error=integ.sync_error,
        monitor_count=_monitor_count(db, integ.id),
    )


def _to_monitor_read(
    m: IntegrationMonitor, integration_name: str = "", is_native: bool = False
) -> IntegrationMonitorRead:
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
        avg_response_ms=m.avg_response_ms,
        cert_expiry_days=m.cert_expiry_days,
        linked_hardware_id=m.linked_hardware_id,
        last_heartbeat_at=m.last_heartbeat_at,
        linked_service_id=m.linked_service_id,
        probe_type=m.probe_type,
        probe_target=m.probe_target,
        probe_port=m.probe_port,
        probe_interval_s=m.probe_interval_s,
        is_native=is_native,
    )


def _get_native_integration(db: Session) -> Integration:
    """Return the singleton native integration, creating it on demand if missing."""
    native = db.query(Integration).filter(Integration.type == "native").first()
    if not native:
        native = Integration(
            type="native",
            name="Built-in Monitors",
            enabled=True,
            sync_interval_s=60,
        )
        db.add(native)
        db.commit()
        db.refresh(native)
    return native


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


@router.patch(
    "/{integration_id}/monitors/{monitor_id}",
    response_model=IntegrationMonitorRead,
)
def update_monitor_link(
    integration_id: int,
    monitor_id: int,
    body: MonitorLinkUpdate,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> IntegrationMonitorRead:
    """Link or unlink a monitor to a CB hardware asset."""
    from sqlalchemy import select

    mon = db.execute(
        select(IntegrationMonitor).where(
            IntegrationMonitor.id == monitor_id,
            IntegrationMonitor.integration_id == integration_id,
        )
    ).scalar_one_or_none()
    if mon is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    if body.linked_hardware_id is not None:
        from app.db.models import Hardware

        hw = db.get(Hardware, body.linked_hardware_id)
        if hw is None:
            raise HTTPException(status_code=404, detail="Hardware asset not found")
    mon.linked_hardware_id = body.linked_hardware_id
    db.commit()
    db.refresh(mon)
    integ = db.get(Integration, integration_id)
    return _to_monitor_read(mon, integ.name if integ else "")


# ── Native monitor endpoints ────────────────────────────────────────────────


@router.get("/native/monitors", response_model=list[IntegrationMonitorRead])
def list_native_monitors(db: Session = Depends(get_db)) -> list[IntegrationMonitorRead]:
    """List all native (built-in) monitors."""
    native = _get_native_integration(db)
    monitors = (
        db.query(IntegrationMonitor)
        .filter(IntegrationMonitor.integration_id == native.id)
        .order_by(IntegrationMonitor.name)
        .all()
    )
    return [_to_monitor_read(m, native.name, is_native=True) for m in monitors]


@router.post("/native/monitors", response_model=IntegrationMonitorRead, status_code=201)
def create_native_monitor(
    body: NativeMonitorCreate,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> IntegrationMonitorRead:
    """Create a native probe monitor from a hardware or service entity."""
    from app.integrations.native_probe import derive_probe_config

    native = _get_native_integration(db)

    # Resolve entity and derive probe config
    if body.entity_type == "hardware":
        from app.db.models import Hardware

        entity = db.get(Hardware, body.entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Hardware not found")
        default_name = entity.name
        probe_type, probe_target, probe_port = derive_probe_config(hardware=entity)
        linked_hardware_id = entity.id
        linked_service_id = None
    else:
        from app.db.models import Service

        svc_entity = db.get(Service, body.entity_id)
        if svc_entity is None:
            raise HTTPException(status_code=404, detail="Service not found")
        default_name = svc_entity.name
        probe_type, probe_target, probe_port = derive_probe_config(service=svc_entity)
        linked_hardware_id = None
        linked_service_id = svc_entity.id

    # Check for duplicate
    existing = (
        db.query(IntegrationMonitor)
        .filter(
            IntegrationMonitor.integration_id == native.id,
            IntegrationMonitor.linked_hardware_id == linked_hardware_id
            if linked_hardware_id
            else IntegrationMonitor.linked_service_id == linked_service_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Monitor already exists for this entity")

    # Apply body overrides
    final_probe_type = body.probe_type or probe_type
    final_probe_target = body.probe_target or probe_target
    final_probe_port = body.probe_port if body.probe_port is not None else probe_port

    if not final_probe_target:
        raise HTTPException(
            status_code=422,
            detail="Cannot derive probe target — entity has no IP address, hostname, or URL.",
        )

    monitor = IntegrationMonitor(
        integration_id=native.id,
        external_id=f"native-{'hw' if body.entity_type == 'hardware' else 'svc'}-{entity.id}",
        name=body.name or default_name,
        probe_type=final_probe_type,
        probe_target=final_probe_target,
        probe_port=final_probe_port,
        probe_interval_s=body.probe_interval_s,
        linked_hardware_id=linked_hardware_id,
        linked_service_id=linked_service_id,
        status="pending",
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    # Auto-add to a default status group so it's immediately visible
    try:
        _auto_add_to_status_group(db, monitor)
    except Exception:
        _logger.debug("Auto-add monitor %d to status group failed (non-critical)", monitor.id)

    return _to_monitor_read(monitor, native.name, is_native=True)


def _auto_add_to_status_group(db: Session, monitor: IntegrationMonitor) -> None:
    """Add a newly-created monitor to a default 'Monitors' status group."""
    page = db.query(StatusPage).first()
    if not page:
        page = StatusPage(name="Infrastructure", slug="infrastructure", is_public=False)
        db.add(page)
        db.flush()

    group = (
        db.query(StatusGroup)
        .filter(StatusGroup.status_page_id == page.id, StatusGroup.name == "Monitors")
        .first()
    )
    if not group:
        group = StatusGroup(status_page_id=page.id, name="Monitors", nodes=[], services=[])
        db.add(group)
        db.flush()

    nodes = list(group.nodes or [])
    entry = {"type": "integration_monitor", "id": monitor.id}
    if not any(n.get("type") == "integration_monitor" and n.get("id") == monitor.id for n in nodes):
        nodes.append(entry)
        group.nodes = nodes
        db.commit()


@router.delete("/native/monitors/{monitor_id}", status_code=204)
def delete_native_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
    _auth: Any = Depends(require_write_auth),
) -> None:
    """Delete a native monitor."""
    native = _get_native_integration(db)
    mon = (
        db.query(IntegrationMonitor)
        .filter(
            IntegrationMonitor.id == monitor_id,
            IntegrationMonitor.integration_id == native.id,
        )
        .first()
    )
    if mon is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    db.delete(mon)
    db.commit()


@router.patch(
    "/monitors/events/{event_id}",
    response_model=IntegrationMonitorEventRead,
)
def annotate_monitor_event(
    event_id: int,
    body: EventAnnotate,
    db: Session = Depends(get_db),
    auth: Any = Depends(require_write_auth),
) -> IntegrationMonitorEventRead:
    """Add or update an admin annotation on a monitor status-change event."""
    from app.core.time import utcnow

    event = db.get(IntegrationMonitorEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Extract user ID from auth token
    user_id: int | None = None
    if hasattr(auth, "id"):
        user_id = auth.id
    elif isinstance(auth, dict):
        user_id = auth.get("id")

    event.reason = body.reason
    event.reason_by = user_id
    event.reason_at = utcnow()
    db.commit()
    db.refresh(event)
    return IntegrationMonitorEventRead(
        id=event.id,
        monitor_id=event.monitor_id,
        previous_status=event.previous_status,
        new_status=event.new_status,
        detected_at=event.detected_at,
        reason=event.reason,
        reason_by=event.reason_by,
        reason_at=event.reason_at,
    )
