import json
import logging

from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from fastapi import HTTPException

from app.db.models import Hardware, HardwareNetwork, Network, ComputeUnit, Storage, Service, EntityTag, Tag
from app.schemas.hardware import HardwareCreate, HardwareUpdate
from app.services.environments_service import resolve_environment_id
from app.services.ip_reservation import check_ip_conflict, bulk_conflict_map
from app.services.log_service import write_log
from app.core.time import utcnow

_logger = logging.getLogger(__name__)


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    """Upsert tags and sync EntityTag rows for the given entity."""
    existing = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
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
    rows = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
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
            stmt.join(EntityTag, (EntityTag.entity_type == "hardware") & (EntityTag.entity_id == Hardware.id))
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
                detail={"detail": "IP conflict detected", "conflicts": [c.to_dict() for c in conflicts]},
            )
    telemetry_config_json = None
    if payload.telemetry_config is not None:
        telemetry_config_json = payload.telemetry_config.model_dump_json()
    resolved_env_id = resolve_environment_id(db, payload.environment_id, payload.environment)
    hw = Hardware(
        name=payload.name,
        role=payload.role,
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
        vendor_catalog_key=payload.vendor_catalog_key,
        model_catalog_key=payload.model_catalog_key,
        u_height=payload.u_height,
        rack_unit=payload.rack_unit,
        telemetry_config=telemetry_config_json,
        environment_id=resolved_env_id,
    )
    db.add(hw)
    db.flush()
    _sync_tags(db, "hardware", hw.id, payload.tags)
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
                detail={"detail": "IP conflict detected", "conflicts": [c.to_dict() for c in conflicts]},
            )
    update_data = payload.model_dump(exclude_unset=True, exclude={"tags"})
    # Serialize TelemetryConfig Pydantic model to JSON string for storage
    if "telemetry_config" in update_data and update_data["telemetry_config"] is not None:
        tc = payload.telemetry_config
        update_data["telemetry_config"] = tc.model_dump_json() if hasattr(tc, "model_dump_json") else json.dumps(update_data["telemetry_config"])
    # Resolve environment from inline name or id
    env_str = update_data.pop("environment", None)
    env_id = update_data.pop("environment_id", None)
    if env_str is not None or env_id is not None:
        update_data["environment_id"] = resolve_environment_id(db, env_id, env_str)
    for field, value in update_data.items():
        setattr(hw, field, value)
    hw.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "hardware", hw.id, payload.tags)
    db.commit()
    db.refresh(hw)
    return _to_dict(db, hw)


def delete_hardware(db: Session, hardware_id: int) -> None:
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    # Block if dependent entities still exist
    blocking: list[str] = []
    cu_count = len(db.execute(select(ComputeUnit).where(ComputeUnit.hardware_id == hardware_id)).scalars().all())
    if cu_count:
        blocking.append(f"{cu_count} compute unit(s)")
    st_count = len(db.execute(select(Storage).where(Storage.hardware_id == hardware_id)).scalars().all())
    if st_count:
        blocking.append(f"{st_count} storage item(s)")
    svc_count = len(db.execute(select(Service).where(Service.hardware_id == hardware_id)).scalars().all())
    if svc_count:
        blocking.append(f"{svc_count} service(s)")
    if blocking:
        raise ValueError(
            f"Cannot delete: this hardware has {', '.join(blocking)} assigned to it. Remove them first."
        )
    # Cascade-remove network memberships (join table, safe to auto-remove)
    for row in db.execute(select(HardwareNetwork).where(HardwareNetwork.hardware_id == hardware_id)).scalars().all():
        db.delete(row)
    # Null out gateway references from any networks pointing here
    for net in db.execute(select(Network).where(Network.gateway_hardware_id == hardware_id)).scalars().all():
        net.gateway_hardware_id = None
    db.flush()
    _sync_tags(db, "hardware", hw.id, [])
    db.delete(hw)
    db.commit()


def list_network_memberships(db: Session, hardware_id: int) -> list[dict]:
    """Return all networks this hardware node directly belongs to (via HardwareNetwork)."""
    rows = db.execute(
        select(HardwareNetwork).where(HardwareNetwork.hardware_id == hardware_id)
    ).scalars().all()
    result = []
    for hn in rows:
        net = db.get(Network, hn.network_id)
        result.append({
            "id": hn.id,
            "network_id": hn.network_id,
            "ip_address": hn.ip_address,
            "network": {
                "name": net.name if net else None,
                "cidr": net.cidr if net else None,
                "vlan_id": net.vlan_id if net else None,
                "gateway": net.gateway if net else None,
            } if net else None,
        })
    return result
