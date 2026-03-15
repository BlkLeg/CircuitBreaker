"""
Batch import service: converts ScanResult rows into Hardware rows.

Deduplicates by MAC address first, then IP address.
All upserts execute in a single SAVEPOINT (begin_nested) for atomicity.
Computes subnet-grouped layout for newly created nodes and persists it server-side.
Idempotent: re-importing the same scan produces updated rows, not duplicates.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Hardware, ScanResult
from app.schemas.discovery import (
    BatchImportConflict,
    BatchImportCreated,
    BatchImportRequest,
    BatchImportResponse,
)
from app.services.inference_service import annotate_result
from app.services.layout_service import compute_subnet_layout

_logger = logging.getLogger(__name__)

_VALID_ROLES = {
    "server",
    "router",
    "switch",
    "firewall",
    "hypervisor",
    "storage",
    "compute",
    "access_point",
    "sbc",
    "ups",
    "pdu",
    "misc",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitise_overrides(overrides: dict) -> dict:
    allowed = {"name", "role", "vendor", "vendor_icon_slug", "notes"}
    clean = {k: v for k, v in overrides.items() if k in allowed}
    if "role" in clean and clean["role"] not in _VALID_ROLES:
        del clean["role"]
    return clean


def batch_import(
    db: Session,
    job_id: int,
    request: BatchImportRequest,
    actor: str = "api",
) -> BatchImportResponse:
    response = BatchImportResponse()

    with db.begin_nested():
        for item in request.items:
            scan_result = db.get(ScanResult, item.scan_result_id)
            if not scan_result or scan_result.scan_job_id != job_id:
                response.skipped.append(item.scan_result_id)
                continue

            ip = scan_result.ip_address
            mac = scan_result.mac_address

            # Lock candidate rows to prevent concurrent duplicate creation
            hw_by_mac: Hardware | None = None
            hw_by_ip: Hardware | None = None

            if mac:
                hw_by_mac = db.execute(
                    select(Hardware).where(Hardware.mac_address == mac).with_for_update()
                ).scalar_one_or_none()
            if ip:
                hw_by_ip = db.execute(
                    select(Hardware).where(Hardware.ip_address == ip).with_for_update()
                ).scalar_one_or_none()

            # Detect cross-match conflict: MAC resolves to different row than IP
            if hw_by_mac and hw_by_ip and hw_by_mac.id != hw_by_ip.id:
                response.conflicts.append(
                    BatchImportConflict(
                        scan_result_id=item.scan_result_id,
                        ip=ip,
                        mac=mac,
                        reason=f"mac_matches_id_{hw_by_mac.id}_ip_matches_id_{hw_by_ip.id}",
                    )
                )
                continue

            existing = hw_by_mac or hw_by_ip
            overrides = _sanitise_overrides(item.overrides)

            if existing:
                existing.last_seen = _now_iso()
                if mac and existing.mac_address != mac:
                    existing.mac_address = mac
                if scan_result.hostname and existing.name != scan_result.hostname:
                    existing.name = scan_result.hostname
                # Only overwrite discovery-sourced fields to preserve manual edits
                if getattr(existing, "source", None) == "discovery":
                    for k, v in overrides.items():
                        setattr(existing, k, v)
                existing.source_scan_result_id = scan_result.id
                db.flush()
                # IPAM auto-reserve
                if ip:
                    from app.services.settings_service import get_or_create_settings

                    settings = get_or_create_settings(db)
                    if settings.ipam_auto_reserve:
                        from app.services.ip_reservation import auto_reserve_ip, record_conflict

                        if settings.ipam_reserve_mode == "auto":
                            hw_id = existing.id
                            reserved = auto_reserve_ip(
                                db,
                                hw_id,
                                ip,
                                scan_result.hostname,
                                getattr(settings, "tenant_id", None),
                            )
                            if reserved is None:
                                record_conflict(
                                    db,
                                    ip,
                                    "hardware",
                                    hw_id,
                                    "hardware",
                                    0,
                                    tenant_id=getattr(settings, "tenant_id", None),
                                )
                        elif settings.ipam_reserve_mode == "approval":
                            from app.db.models import IPReservationQueue

                            hw_id = existing.id
                            queue_entry = IPReservationQueue(
                                hardware_id=hw_id,
                                ip_address=ip,
                                hostname=scan_result.hostname,
                                status="pending",
                            )
                            db.add(queue_entry)
                            db.flush()
                response.updated.append(BatchImportCreated(id=existing.id, ip=ip))
            else:
                ann = annotate_result(scan_result)
                name = (
                    overrides.pop("name", None)
                    or scan_result.hostname
                    or ip
                    or f"device-{scan_result.id}"
                )
                hw = Hardware(
                    name=name,
                    ip_address=ip,
                    mac_address=mac,
                    hostname=scan_result.hostname,
                    role=overrides.pop("role", None) or ann.role or "misc",
                    vendor=overrides.pop("vendor", None) or ann.vendor,
                    vendor_icon_slug=overrides.pop("vendor_icon_slug", None)
                    or ann.vendor_icon_slug,
                    source="discovery",
                    discovered_at=_now_iso(),
                    last_seen=_now_iso(),
                    source_scan_result_id=scan_result.id,
                    node_type="hardware",
                )
                for k, v in overrides.items():
                    setattr(hw, k, v)
                db.add(hw)
                db.flush()
                # IPAM auto-reserve
                if ip:
                    from app.services.settings_service import get_or_create_settings

                    settings = get_or_create_settings(db)
                    if settings.ipam_auto_reserve:
                        from app.services.ip_reservation import auto_reserve_ip, record_conflict

                        if settings.ipam_reserve_mode == "auto":
                            hw_id = hw.id
                            reserved = auto_reserve_ip(
                                db,
                                hw_id,
                                ip,
                                scan_result.hostname,
                                getattr(settings, "tenant_id", None),
                            )
                            if reserved is None:
                                record_conflict(
                                    db,
                                    ip,
                                    "hardware",
                                    hw_id,
                                    "hardware",
                                    0,
                                    tenant_id=getattr(settings, "tenant_id", None),
                                )
                        elif settings.ipam_reserve_mode == "approval":
                            from app.db.models import IPReservationQueue

                            hw_id = hw.id
                            queue_entry = IPReservationQueue(
                                hardware_id=hw_id,
                                ip_address=ip,
                                hostname=scan_result.hostname,
                                status="pending",
                            )
                            db.add(queue_entry)
                            db.flush()
                response.created.append(BatchImportCreated(id=hw.id, ip=ip))

    # Compute layout for newly created nodes only (updated nodes keep their positions)
    if response.created:
        hw_list = []
        for c in response.created:
            hw_obj = db.get(Hardware, c.id)
            if hw_obj:
                hw_list.append({"id": c.id, "ip_address": c.ip, "role": hw_obj.role})
        positions = compute_subnet_layout(hw_list)
        for created_item in response.created:
            created_item.position = positions.get(created_item.id)
        _persist_layout(db, positions)

    db.commit()
    return response


def _persist_layout(db: Session, positions: dict[int, dict]) -> None:
    """Save positions to the graph layout table (server-side, non-fatal on failure)."""
    try:
        from app.db.models import GraphLayout

        str_positions = {str(k): v for k, v in positions.items()}
        layout = db.query(GraphLayout).filter(GraphLayout.name == "default").first()
        if layout:
            layout.layout_data = str_positions
        else:
            layout = GraphLayout(name="default", layout_data=str_positions)
            db.add(layout)
        db.flush()
    except Exception as exc:
        _logger.warning("Layout persistence failed (non-fatal): %s", exc)
