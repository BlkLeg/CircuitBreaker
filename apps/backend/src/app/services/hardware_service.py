import json
import logging
import re

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import (  # noqa: F401 (Service used for reactive cascade)
    ComputeUnit,
    EntityTag,
    Hardware,
    HardwareClusterMember,
    HardwareConnection,
    HardwareMonitor,
    HardwareNetwork,
    Network,
    Service,
    Storage,
    Tag,
    UptimeEvent,
)
from app.schemas.hardware import HardwareCreate, HardwareUpdate
from app.services.environments_service import resolve_environment_id
from app.services.ip_reservation import bulk_conflict_map, check_ip_conflict, resolve_ip_conflict
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)


def _norm_mac(mac: str | None) -> str | None:
    """Normalize a MAC address to uppercase colon-separated format (AA:BB:CC:DD:EE:FF).
    Returns None if input is None or empty."""
    if not mac:
        return None
    cleaned = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(cleaned) != 12:
        return mac.strip().upper()  # Can't normalize — return uppercased original
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2)).upper()


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    """Upsert tags and sync EntityTag rows for the given entity."""
    existing = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    for et in existing:
        db.delete(et)
    db.flush()

    for name in tag_names:
        tag = db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(EntityTag(entity_type=entity_type, entity_id=entity_id, tag_id=tag.id))


def get_tags_for(db: Session, entity_type: str, entity_id: int) -> list[str]:
    rows = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    return [row.tag.name for row in rows]


def _to_dict(db: Session, hw: Hardware) -> dict:
    d = {c.name: getattr(hw, c.name) for c in hw.__table__.columns}
    d["tags"] = get_tags_for(db, "hardware", hw.id)
    # Deserialize JSON text columns into dicts for API responses
    if isinstance(d.get("telemetry_config"), str):
        try:
            d["telemetry_config"] = json.loads(d["telemetry_config"])
        except (json.JSONDecodeError, TypeError):
            d["telemetry_config"] = None
    if isinstance(d.get("telemetry_data"), str):
        try:
            d["telemetry_data"] = json.loads(d["telemetry_data"])
        except (json.JSONDecodeError, TypeError):
            d["telemetry_data"] = {}

    # Deserialize networking extensions (v0.1.7)
    for field in ("wifi_standards", "wifi_bands", "port_map_json"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = [] if field != "port_map_json" else []

    # Expose port_map_json as port_map in the API
    d["port_map"] = d.pop("port_map_json", [])

    if hw.storage_items:
        total_gb = sum(s.capacity_gb or 0 for s in hw.storage_items)
        used_gb_vals = [s.used_gb for s in hw.storage_items if s.used_gb is not None]
        kinds = list(dict.fromkeys(s.kind for s in hw.storage_items if s.kind))
        d["storage_summary"] = {
            "total_gb": total_gb,
            "used_gb": sum(used_gb_vals) if used_gb_vals else None,
            "types": kinds,
            "primary_pool": hw.storage_items[0].name,
            "count": len(hw.storage_items),
        }
    else:
        d["storage_summary"] = None
    d["environment_name"] = hw.environment_rel.name if hw.environment_rel else None
    d["rack_name"] = hw.rack.name if hw.rack else None
    return d


def list_hardware(
    db: Session,
    *,
    tag: str | None = None,
    role: str | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Hardware)
    if role:
        stmt = stmt.where(Hardware.role == role)
    if q:
        stmt = stmt.where(or_(Hardware.name.ilike(f"%{q}%"), Hardware.notes.ilike(f"%{q}%")))
    if tag:
        stmt = (
            stmt.join(
                EntityTag,
                (EntityTag.entity_type == "hardware") & (EntityTag.entity_id == Hardware.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    conflict_map = bulk_conflict_map(db)
    result = []
    for r in rows:
        d = _to_dict(db, r)
        d["ip_conflict"] = conflict_map.get(("hardware", r.id), False)
        result.append(d)
    return result


def get_hardware(db: Session, hardware_id: int) -> dict:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    d = _to_dict(db, hw)
    if hw.ip_address:
        conflicts = check_ip_conflict(
            db,
            ip=hw.ip_address,
            ports=None,
            exclude_entity_type="hardware",
            exclude_entity_id=hardware_id,
        )
        d["ip_conflict"] = len(conflicts) > 0
        d["ip_conflict_details"] = [c.to_dict() for c in conflicts]
    else:
        d["ip_conflict"] = False
        d["ip_conflict_details"] = []
    return d


def _sync_port_edges(db: Session, hardware_id: int, port_map: list) -> None:
    """Sync 'connects_to' graph edges based on port map connectivity."""
    from app.services.graph_service import create_edge  # type: ignore[attr-defined]

    for p in port_map:
        data = p.model_dump() if hasattr(p, "model_dump") else p
        target_hw_id = data.get("connected_hardware_id")
        target_cu_id = data.get("connected_compute_id")

        if target_hw_id:
            create_edge(db, "hardware", hardware_id, "hardware", target_hw_id, "connects_to")
        if target_cu_id:
            create_edge(db, "hardware", hardware_id, "compute", target_cu_id, "connects_to")


def create_hardware(db: Session, payload: HardwareCreate) -> dict:
    if payload.ip_address:
        conflicts = check_ip_conflict(
            db,
            ip=payload.ip_address,
            ports=None,
            exclude_entity_type="hardware",
            exclude_entity_id=None,
        )
        if conflicts:
            _logger.warning(
                "IP conflict blocked save for hardware %r: %s already used by %s",
                payload.name,
                payload.ip_address,
                ", ".join(c.entity_name for c in conflicts),
            )
            write_log(
                db,
                action="ip_conflict",
                entity_type="hardware",
                entity_name=payload.name,
                severity="warn",
                details=f"IP conflict for {payload.ip_address}: already used by {', '.join(c.entity_name for c in conflicts)}",
                category="crud",
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "IP conflict detected",
                    "conflicts": [c.to_dict() for c in conflicts],
                },
            )

    # CB-LEARN-002: auto-fill u_height/role from catalog when null but catalog keys present
    u_height = payload.u_height
    role = payload.role
    rack_id = payload.rack_id
    if payload.vendor_catalog_key and payload.model_catalog_key:
        from app.services.catalog_service import get_device_spec

        spec = get_device_spec(payload.vendor_catalog_key, payload.model_catalog_key)
        if spec:
            if u_height is None and spec.get("u_height"):
                u_height = spec["u_height"]
            if role is None and spec.get("role"):
                role = spec["role"]

    # CB-RACK-002: rack overlap check
    rack_unit = payload.rack_unit
    if rack_id is not None and rack_unit is not None and u_height is not None:
        from app.services.rack_service import check_rack_overlap

        overlaps = check_rack_overlap(db, rack_id, rack_unit, u_height)
        if overlaps:
            raise HTTPException(
                status_code=422,
                detail={"detail": "Rack slot overlap", "conflicts": overlaps},
            )

    # CB-PATTERN-001: MAC normalization + soft-alert on duplicate
    mac = _norm_mac(getattr(payload, "mac_address", None))
    if mac:
        existing = db.execute(
            select(Hardware).where(Hardware.mac_address == mac)
        ).scalar_one_or_none()
        if existing:
            _logger.warning(
                "Duplicate MAC detected for new hardware %r: conflicts with existing hardware id=%d %r. Saving both (freeform-first).",
                payload.name,
                existing.id,
                existing.name,
            )

    telemetry_config_json = None
    if payload.telemetry_config is not None:
        telemetry_config_json = payload.telemetry_config.model_dump_json()
    resolved_env_id = resolve_environment_id(db, payload.environment_id, payload.environment)
    hw = Hardware(
        name=payload.name,
        role=role,
        vendor=payload.vendor,
        model=payload.model,
        cpu=payload.cpu,
        memory_gb=payload.memory_gb,
        location=payload.location,
        notes=payload.notes,
        ip_address=payload.ip_address,
        wan_uplink=payload.wan_uplink,
        cpu_brand=payload.cpu_brand,
        vendor_icon_slug=payload.vendor_icon_slug,
        custom_icon=payload.custom_icon,
        vendor_catalog_key=payload.vendor_catalog_key,
        model_catalog_key=payload.model_catalog_key,
        u_height=u_height,
        rack_unit=rack_unit,
        telemetry_config=telemetry_config_json,
        environment_id=resolved_env_id,
        rack_id=rack_id,
        # v0.1.7: Networking extensions
        wifi_standards=json.dumps(payload.wifi_standards) if payload.wifi_standards else None,
        wifi_bands=json.dumps(payload.wifi_bands) if payload.wifi_bands else None,
        max_tx_power_dbm=payload.max_tx_power_dbm,
        port_count=payload.port_count,
        port_map_json=json.dumps(
            [p.model_dump() if hasattr(p, "model_dump") else p for p in payload.port_map]
        )
        if payload.port_map
        else None,
        software_platform=payload.software_platform,
        download_speed_mbps=payload.download_speed_mbps,
        upload_speed_mbps=payload.upload_speed_mbps,
    )
    db.add(hw)
    db.flush()
    _sync_tags(db, "hardware", hw.id, payload.tags)
    # CB-PORTMAP-001: Sync graph edges from port map
    if payload.port_map:
        _sync_port_edges(db, hw.id, payload.port_map)
    db.commit()
    db.refresh(hw)
    return _to_dict(db, hw)


def update_hardware(db: Session, hardware_id: int, payload: HardwareUpdate) -> dict:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    effective_ip = payload.ip_address if payload.ip_address is not None else hw.ip_address
    if effective_ip:
        conflicts = check_ip_conflict(
            db,
            ip=effective_ip,
            ports=None,
            exclude_entity_type="hardware",
            exclude_entity_id=hardware_id,
        )
        if conflicts:
            _logger.warning(
                "IP conflict blocked save for hardware %r: %s already used by %s",
                hw.name,
                effective_ip,
                ", ".join(c.entity_name for c in conflicts),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": "IP conflict detected",
                    "conflicts": [c.to_dict() for c in conflicts],
                },
            )
    update_data = payload.model_dump(exclude_unset=True, exclude={"tags", "port_map"})
    # Serialize TelemetryConfig Pydantic model to JSON string for storage
    if "telemetry_config" in payload.model_fields_set and payload.telemetry_config is not None:
        tc = payload.telemetry_config
        update_data["telemetry_config"] = (
            tc.model_dump_json() if hasattr(tc, "model_dump_json") else json.dumps(tc)
        )

    # Serialize networking extensions (v0.1.7)
    if "wifi_standards" in payload.model_fields_set and payload.wifi_standards is not None:
        update_data["wifi_standards"] = json.dumps(payload.wifi_standards)
    if "wifi_bands" in payload.model_fields_set and payload.wifi_bands is not None:
        update_data["wifi_bands"] = json.dumps(payload.wifi_bands)

    if "port_map" in payload.model_fields_set:
        if payload.port_map is not None:
            update_data["port_map_json"] = json.dumps(
                [p.model_dump() if hasattr(p, "model_dump") else p for p in payload.port_map]
            )
            _sync_port_edges(db, hardware_id, payload.port_map)
        else:
            update_data["port_map_json"] = None

    # Resolve environment from inline name or id
    env_str = update_data.pop("environment", None)
    env_id = update_data.pop("environment_id", None)
    if env_str is not None or env_id is not None:
        update_data["environment_id"] = resolve_environment_id(db, env_id, env_str)

    # CB-RACK-002: rack overlap check on update
    effective_rack_id = update_data.get("rack_id", hw.rack_id)
    effective_rack_unit = update_data.get("rack_unit", hw.rack_unit)
    effective_u_height = update_data.get("u_height", hw.u_height)
    if (
        effective_rack_id is not None
        and effective_rack_unit is not None
        and effective_u_height is not None
    ):
        from app.services.rack_service import check_rack_overlap

        overlaps = check_rack_overlap(
            db,
            effective_rack_id,
            effective_rack_unit,
            effective_u_height,
            exclude_hardware_id=hardware_id,
        )
        if overlaps:
            raise HTTPException(
                status_code=422,
                detail={"detail": "Rack slot overlap", "conflicts": overlaps},
            )

    for field, value in update_data.items():
        setattr(hw, field, value)
    # CB-STATE-005: touch last_seen on any update
    hw.last_seen = utcnow().isoformat()
    hw.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "hardware", hw.id, payload.tags)
    db.commit()
    db.refresh(hw)
    # Re-evaluate services directly on this hardware
    affected: list[Service] = list(
        db.execute(select(Service).where(Service.hardware_id == hardware_id)).scalars().all()
    )
    # Also services on compute units hosted by this hardware
    cus = (
        db.execute(select(ComputeUnit).where(ComputeUnit.hardware_id == hardware_id))
        .scalars()
        .all()
    )
    for cu in cus:
        affected += list(
            db.execute(select(Service).where(Service.compute_id == cu.id)).scalars().all()
        )
    for svc in affected:
        result = resolve_ip_conflict(db, svc.id, svc.ip_address, svc.compute_id, svc.hardware_id)
        svc.ip_mode = result["ip_mode"]
        svc.ip_conflict = result["is_conflict"]
        svc.ip_conflict_json = result["conflict_with"]
    if affected:
        db.commit()
    # CB-STATE-001: recalculate hardware status (respects status_override)
    from app.services.status_service import recalculate_hardware_status

    recalculate_hardware_status(db, hardware_id)
    db.commit()
    return _to_dict(db, hw)


def delete_hardware(db: Session, hardware_id: int) -> None:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    # Release IPAM reservations if enabled
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db)
    if settings.ipam_release_on_delete:
        from app.services.ip_reservation import release_hardware_ips

        release_hardware_ips(db, hardware_id)
    # Block if dependent entities still exist
    blocking: list[str] = []
    cu_count = len(
        db.execute(select(ComputeUnit).where(ComputeUnit.hardware_id == hardware_id))
        .scalars()
        .all()
    )
    if cu_count:
        blocking.append(f"{cu_count} compute unit(s)")
    st_count = len(
        db.execute(select(Storage).where(Storage.hardware_id == hardware_id)).scalars().all()
    )
    if st_count:
        blocking.append(f"{st_count} storage item(s)")
    svc_count = len(
        db.execute(select(Service).where(Service.hardware_id == hardware_id)).scalars().all()
    )
    if svc_count:
        blocking.append(f"{svc_count} service(s)")
    if blocking:
        raise ValueError(
            f"Cannot delete: this hardware has {', '.join(blocking)} assigned to it. Remove them first."
        )
    # ── Safe cascades (join/history tables — no user data lost) ──────────────

    # Network memberships
    for row in (
        db.execute(select(HardwareNetwork).where(HardwareNetwork.hardware_id == hardware_id))
        .scalars()
        .all()
    ):
        db.delete(row)
    # Null out gateway references from networks pointing here
    for net in (
        db.execute(select(Network).where(Network.gateway_hardware_id == hardware_id))
        .scalars()
        .all()
    ):
        net.gateway_hardware_id = None
    # Cluster memberships (removes device from any cluster; clusters themselves are kept)
    for row in (  # type: ignore[assignment]
        db.execute(
            select(HardwareClusterMember).where(HardwareClusterMember.hardware_id == hardware_id)
        )
        .scalars()
        .all()
    ):
        db.delete(row)
    # Physical connections (both directions)
    for row in (  # type: ignore[assignment]
        db.execute(
            select(HardwareConnection).where(
                (HardwareConnection.source_hardware_id == hardware_id)
                | (HardwareConnection.target_hardware_id == hardware_id)
            )
        )
        .scalars()
        .all()
    ):
        db.delete(row)
    # Uptime monitor + event history
    for row in (  # type: ignore[assignment]
        db.execute(select(UptimeEvent).where(UptimeEvent.hardware_id == hardware_id))
        .scalars()
        .all()
    ):
        db.delete(row)
    monitor = db.execute(
        select(HardwareMonitor).where(HardwareMonitor.hardware_id == hardware_id)
    ).scalar_one_or_none()
    if monitor:
        db.delete(monitor)

    db.flush()
    _sync_tags(db, "hardware", hw.id, [])
    db.delete(hw)
    db.commit()


def find_orphans(db: Session) -> list[dict]:
    """CB-PATTERN-003: Find hardware with no compute_units, services, or storage attached."""
    all_hw = db.execute(select(Hardware)).scalars().all()
    orphans = []
    for hw in all_hw:
        has_cu = db.execute(
            select(ComputeUnit.id).where(ComputeUnit.hardware_id == hw.id).limit(1)
        ).first()
        has_svc = db.execute(
            select(Service.id).where(Service.hardware_id == hw.id).limit(1)
        ).first()
        has_st = db.execute(select(Storage.id).where(Storage.hardware_id == hw.id).limit(1)).first()
        if not has_cu and not has_svc and not has_st:
            orphans.append(_to_dict(db, hw))
    return orphans


def list_hardware_groups(db: Session) -> list[dict]:
    """CB-PATTERN-004: Group hardware by vendor+model with counts."""
    rows = db.execute(
        select(
            Hardware.vendor,
            Hardware.model,
            func.count(Hardware.id).label("count"),
        ).group_by(Hardware.vendor, Hardware.model)
    ).all()
    return [{"vendor": r.vendor, "model": r.model, "count": r.count} for r in rows]


def add_hardware_connection(db: Session, source_id: int, target_id: int) -> dict:
    """Create a direct hardware-to-hardware physical connection."""
    get_hardware(db, source_id)  # 404 guard
    get_hardware(db, target_id)  # 404 guard
    conn = HardwareConnection(
        source_hardware_id=source_id,
        target_hardware_id=target_id,
        connection_type="ethernet",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return {
        "id": conn.id,
        "source_hardware_id": conn.source_hardware_id,
        "target_hardware_id": conn.target_hardware_id,
        "connection_type": conn.connection_type,
        "bandwidth_mbps": conn.bandwidth_mbps,
    }


def remove_hardware_connection(db: Session, connection_id: int) -> dict:
    """Delete a hardware-to-hardware connection by its ID.

    Returns the connection details captured before deletion so callers can
    publish topology events with the source/target IDs.
    """
    conn = db.get(HardwareConnection, connection_id)
    if conn is None:
        raise ValueError(f"Hardware connection {connection_id} not found.")
    details = {
        "id": conn.id,
        "source_hardware_id": conn.source_hardware_id,
        "target_hardware_id": conn.target_hardware_id,
        "connection_type": conn.connection_type,
    }
    db.delete(conn)
    db.commit()
    return details


def update_hardware_connection_type(db: Session, connection_id: int, connection_type: str) -> dict:
    """Update the connection_type on a hardware-to-hardware link."""
    conn = db.get(HardwareConnection, connection_id)
    if conn is None:
        raise ValueError(f"Hardware connection {connection_id} not found.")
    conn.connection_type = connection_type
    db.commit()
    db.refresh(conn)
    return {"id": conn.id, "connection_type": conn.connection_type}


def list_network_memberships(db: Session, hardware_id: int) -> list[dict]:
    """Return all networks this hardware node directly belongs to (via HardwareNetwork)."""
    rows = (
        db.execute(select(HardwareNetwork).where(HardwareNetwork.hardware_id == hardware_id))
        .scalars()
        .all()
    )
    result = []
    for hn in rows:
        net = db.get(Network, hn.network_id)
        result.append(
            {
                "id": hn.id,
                "network_id": hn.network_id,
                "ip_address": hn.ip_address,
                "network": {
                    "name": net.name if net else None,
                    "cidr": net.cidr if net else None,
                    "vlan_id": net.vlan_id if net else None,
                    "gateway": net.gateway if net else None,
                }
                if net
                else None,
            }
        )
    return result
