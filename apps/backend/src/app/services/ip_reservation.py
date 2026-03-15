"""IP/port conflict detection across hardware, compute units, and services."""

from __future__ import annotations

import ipaddress as _ipaddress
import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeUnit, Hardware, IPAddress, IPConflict, Network, Service

_logger = logging.getLogger(__name__)


@dataclass
class ConflictResult:
    entity_type: str  # "hardware" | "compute_unit" | "service"
    entity_id: int
    entity_name: str
    conflicting_ip: str
    conflicting_port: int | None
    protocol: str | None

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "conflicting_ip": self.conflicting_ip,
            "conflicting_port": self.conflicting_port,
            "protocol": self.protocol,
        }


def _norm(ip: str | None) -> str | None:
    """Normalise an IP for comparison: strip whitespace, lowercase."""
    if ip is None:
        return None
    return ip.strip().lower()


def _parse_ports_json(raw) -> list[dict]:
    """Return the parsed port-entry list from a ports_json JSONB column value."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.debug("Failed to parse ports JSON: %s", exc)
    return []


def check_ip_conflict(
    db: Session,
    ip: str,
    ports: list[dict] | None = None,
    exclude_entity_type: str | None = None,
    exclude_entity_id: int | None = None,
    incoming_entity_type: str | None = None,
) -> list[ConflictResult]:
    """Return all conflicts for the given IP (and optional port list).

    Conflict rules
    --------------
    1. IP-only conflict — hardware or compute_unit with same ip_address.
       Does NOT apply when the incoming entity is a service (service-on-host is valid).
    2. Service IP:port conflict — any other service whose effective IP + port +
       protocol matches one of the incoming port entries.
    3. Cross-entity portless-service warning — a service whose ip_address matches
       a hardware/compute IP but has no ports defined is flagged as ambiguous.

    Always excludes the entity being edited (exclude_entity_type + exclude_entity_id).
    Pass incoming_entity_type="service" to skip Rule 1 (allows services to share
    an IP with their hardware/compute host).
    """
    norm_ip = _norm(ip)
    if not norm_ip:
        return []

    conflicts: list[ConflictResult] = []

    def _is_self(etype: str, eid: int) -> bool:
        return etype == exclude_entity_type and eid == exclude_entity_id

    # ── Rule 1: hardware/compute IP-only conflicts ──────────────────────────
    # Always checked, even for services.  create_service() decides whether to
    # block on these (it only blocks on service-to-service port clashes).
    for hw in db.execute(select(Hardware)).scalars().all():
        if _is_self("hardware", hw.id):
            continue
        if _norm(hw.ip_address) == norm_ip:
            conflicts.append(
                ConflictResult(
                    entity_type="hardware",
                    entity_id=hw.id,
                    entity_name=hw.name,
                    conflicting_ip=norm_ip,
                    conflicting_port=None,
                    protocol=None,
                )
            )

    for cu in db.execute(select(ComputeUnit)).scalars().all():
        if _is_self("compute_unit", cu.id):
            continue
        if _norm(cu.ip_address) == norm_ip:
            conflicts.append(
                ConflictResult(
                    entity_type="compute_unit",
                    entity_id=cu.id,
                    entity_name=cu.name,
                    conflicting_ip=norm_ip,
                    conflicting_port=None,
                    protocol=None,
                )
            )

    # ── Rules 2 & 3: service conflicts ───────────────────────────────────────
    incoming_ports = ports or []
    # Build a set of (effective_ip, port, protocol) for fast lookup
    # Only include entries with a valid port number
    incoming_bindings: set[tuple[str, int, str]] = set()
    for pe in incoming_ports:
        p_ip = _norm(pe.get("ip")) or norm_ip
        p_port = pe.get("port")
        p_proto = (pe.get("protocol") or "tcp").lower()
        if p_port is not None:
            incoming_bindings.add((p_ip, int(p_port), p_proto))

    for svc in db.execute(select(Service)).scalars().all():
        if _is_self("service", svc.id):
            continue

        svc_ip = _norm(svc.ip_address)
        svc_ports = _parse_ports_json(svc.ports_json)

        # Rule 2: IP:port match against other services
        for pe in svc_ports:
            if pe.get("port") is None:
                continue
            effective_ip = _norm(pe.get("ip")) or svc_ip
            pe_port = int(pe["port"])
            pe_proto = (pe.get("protocol") or "tcp").lower()
            if effective_ip and (effective_ip, pe_port, pe_proto) in incoming_bindings:
                conflicts.append(
                    ConflictResult(
                        entity_type="service",
                        entity_id=svc.id,
                        entity_name=svc.name,
                        conflicting_ip=effective_ip,
                        conflicting_port=pe_port,
                        protocol=pe_proto,
                    )
                )

        # Rule 3: portless service on the same IP as a hardware/compute node
        # Only applies when the incoming entity is hardware or compute_unit (not a service)
        if (
            exclude_entity_type in ("hardware", "compute_unit")
            and svc_ip == norm_ip
            and not svc_ports
        ):
            conflicts.append(
                ConflictResult(
                    entity_type="service",
                    entity_id=svc.id,
                    entity_name=svc.name,
                    conflicting_ip=norm_ip,
                    conflicting_port=None,
                    protocol=None,
                )
            )

    return conflicts


def resolve_ip_conflict(
    db: Session,
    service_id: int | None,
    ip_address: str | None,
    compute_id: int | None,
    hardware_id: int | None,
    ports: list[dict] | None = None,
) -> dict:
    """Host-chain-aware conflict classification for a single service.

    Services sharing an IP with hardware/compute are NOT blocked — services
    naturally run on hosts.  Only service-to-service port collisions (same IP
    + same port + same protocol) set ``is_conflict=True``.  Hardware/compute
    IP overlaps are still reported in *conflict_with* for informational
    purposes.

    Returns:
    {
        "is_conflict": bool,
        "ip_mode": "inherited_from_compute" | "inherited_from_hardware"
                   | "inherited_from_hardware_via_compute" | "explicit" | "none",
        "conflict_with": [{"entity_type", "entity_id", "entity_name", "entity_ip", ...}, ...]
    }
    """
    norm_ip = _norm(ip_address)
    if not norm_ip:
        return {"is_conflict": False, "ip_mode": "none", "conflict_with": []}

    # Build the set of (type, id) pairs that are allowed to share this IP
    allowed: set[tuple[str, int]] = set()
    if service_id:
        allowed.add(("service", service_id))

    cu = None
    if compute_id:
        cu = db.execute(
            select(ComputeUnit).where(ComputeUnit.id == compute_id)
        ).scalar_one_or_none()
        if cu:
            allowed.add(("compute_unit", cu.id))
            if cu.hardware_id:
                allowed.add(("hardware", cu.hardware_id))
    if hardware_id:
        allowed.add(("hardware", hardware_id))

    # Determine ip_mode
    ip_mode = "explicit"
    if compute_id and cu:
        if _norm(cu.ip_address) == norm_ip:
            ip_mode = "inherited_from_compute"
        elif cu.hardware_id:
            hw = db.execute(
                select(Hardware).where(Hardware.id == cu.hardware_id)
            ).scalar_one_or_none()
            if hw and _norm(hw.ip_address) == norm_ip:
                ip_mode = "inherited_from_hardware_via_compute"
    elif hardware_id:
        hw = db.execute(select(Hardware).where(Hardware.id == hardware_id)).scalar_one_or_none()
        if hw and _norm(hw.ip_address) == norm_ip:
            ip_mode = "inherited_from_hardware"

    if ip_mode != "explicit":
        return {"is_conflict": False, "ip_mode": ip_mode, "conflict_with": []}

    # Explicit IP — check for conflicts against other entities
    # Hardware/compute matches are informational; only service port clashes block.
    conflicts: list[dict] = []
    has_port_clash = False

    for hw in db.execute(select(Hardware).where(Hardware.ip_address == ip_address)).scalars().all():
        if ("hardware", hw.id) not in allowed:
            conflicts.append(
                {
                    "entity_type": "hardware",
                    "entity_id": hw.id,
                    "entity_name": hw.name,
                    "entity_ip": hw.ip_address,
                }
            )
    for cu_row in (
        db.execute(select(ComputeUnit).where(ComputeUnit.ip_address == ip_address)).scalars().all()
    ):
        if ("compute_unit", cu_row.id) not in allowed:
            conflicts.append(
                {
                    "entity_type": "compute_unit",
                    "entity_id": cu_row.id,
                    "entity_name": cu_row.name,
                    "entity_ip": cu_row.ip_address,
                }
            )

    # ── Service-to-service: port-level conflict detection ────────────────
    incoming_ports = ports or []
    incoming_bindings: set[tuple[str, int, str]] = set()
    for pe in incoming_ports:
        p_port = pe.get("port") if isinstance(pe, dict) else getattr(pe, "port", None)
        p_proto = (
            pe.get("protocol") if isinstance(pe, dict) else getattr(pe, "protocol", None)
        ) or "tcp"
        if p_port is not None:
            incoming_bindings.add((norm_ip, int(p_port), p_proto.lower()))

    for svc in (
        db.execute(
            select(Service).where(
                Service.ip_address == ip_address,
                Service.id != (service_id or -1),
            )
        )
        .scalars()
        .all()
    ):
        if not incoming_bindings:
            # Incoming service has no ports — IP-only match is still a conflict
            conflicts.append(
                {
                    "entity_type": "service",
                    "entity_id": svc.id,
                    "entity_name": svc.name,
                    "entity_ip": svc.ip_address,
                }
            )
            has_port_clash = True
            continue

        svc_ports = _parse_ports_json(svc.ports_json)
        if not svc_ports:
            # Existing service has no ports — portless overlap is a conflict
            conflicts.append(
                {
                    "entity_type": "service",
                    "entity_id": svc.id,
                    "entity_name": svc.name,
                    "entity_ip": svc.ip_address,
                }
            )
            has_port_clash = True
            continue

        for spe in svc_ports:
            if spe.get("port") is None:
                continue
            spe_port = int(spe["port"])
            spe_proto = (spe.get("protocol") or "tcp").lower()
            svc_ip = _norm(svc.ip_address)
            if svc_ip and (svc_ip, spe_port, spe_proto) in incoming_bindings:
                conflicts.append(
                    {
                        "entity_type": "service",
                        "entity_id": svc.id,
                        "entity_name": svc.name,
                        "entity_ip": svc.ip_address,
                        "conflicting_port": spe_port,
                        "protocol": spe_proto,
                    }
                )
                has_port_clash = True

    return {"is_conflict": has_port_clash, "ip_mode": ip_mode, "conflict_with": conflicts}


def bulk_conflict_map(db: Session) -> dict[tuple[str, int], bool]:
    """Return a mapping of (entity_type, entity_id) -> has_conflict.

    Runs a single pass across all entities; used by the topology endpoint to
    annotate nodes without issuing N individual queries.
    """
    result: dict[tuple[str, int], bool] = {}

    # Collect all IPs per entity type
    hw_objs = db.execute(select(Hardware)).scalars().all()
    cu_objs = db.execute(select(ComputeUnit)).scalars().all()
    svc_objs = db.execute(select(Service)).scalars().all()

    hw_rows = [(hw.id, hw.name, _norm(hw.ip_address)) for hw in hw_objs]
    cu_rows = [(cu.id, cu.name, _norm(cu.ip_address)) for cu in cu_objs]

    # Build quick IP lookups for inherited-IP resolution
    hw_id_to_ip: dict[int, str | None] = {hw.id: _norm(hw.ip_address) for hw in hw_objs}
    cu_id_to_ip: dict[int, str | None] = {cu.id: _norm(cu.ip_address) for cu in cu_objs}
    cu_id_to_hw_id: dict[int, int | None] = {cu.id: cu.hardware_id for cu in cu_objs}

    def _svc_effective_ip(svc: Service) -> str | None:
        """Resolve IP for a service: own ip_address → compute unit IP → hardware IP."""
        own = _norm(svc.ip_address)
        if own:
            return own
        if svc.compute_id:
            cu_ip = cu_id_to_ip.get(svc.compute_id)
            if cu_ip:
                return cu_ip
            hw_id = cu_id_to_hw_id.get(svc.compute_id)
            return hw_id_to_ip.get(hw_id) if hw_id else None
        if svc.hardware_id:
            return hw_id_to_ip.get(svc.hardware_id)
        return None

    svc_rows = [
        (svc.id, svc.name, _svc_effective_ip(svc), _parse_ports_json(svc.ports_json))
        for svc in svc_objs
    ]

    # Build lookup sets: ip -> [(etype, eid)]
    from collections import defaultdict

    ip_to_hw: dict[str, list[int]] = defaultdict(list)
    ip_to_cu: dict[str, list[int]] = defaultdict(list)
    # (ip, port, proto) -> [(svc_id)]
    binding_to_svc: dict[tuple[str, int, str], list[int]] = defaultdict(list)
    svc_ip_to_id: dict[str, list[int]] = defaultdict(list)

    for hw_id, _, hw_ip in hw_rows:
        if hw_ip:
            ip_to_hw[hw_ip].append(hw_id)

    for cu_id, _, cu_ip in cu_rows:
        if cu_ip:
            ip_to_cu[cu_ip].append(cu_id)

    for svc_id, _, svc_eff_ip, svc_ports in svc_rows:
        if svc_eff_ip:
            svc_ip_to_id[svc_eff_ip].append(svc_id)
        for pe in svc_ports:
            if pe.get("port") is None:
                continue
            eff_ip = _norm(pe.get("ip")) or svc_eff_ip
            if eff_ip:
                binding_to_svc[
                    (eff_ip, int(pe["port"]), (pe.get("protocol") or "tcp").lower())
                ].append(svc_id)

    # Hardware conflicts: multiple hardware on same IP
    for hw_id, _, hw_ip in hw_rows:
        if hw_ip and len(ip_to_hw[hw_ip]) > 1:
            result[("hardware", hw_id)] = True

    # Compute conflicts: multiple compute on same IP
    for cu_id, _, cu_ip in cu_rows:
        if cu_ip and len(ip_to_cu[cu_ip]) > 1:
            result[("compute_unit", cu_id)] = True

    # Service conflicts: duplicate (ip, port, protocol) bindings
    for _binding, svc_ids in binding_to_svc.items():
        if len(svc_ids) > 1:
            for sid in svc_ids:
                result[("service", sid)] = True

    # Portless services: only flag if their OWN ip_address (not inherited) conflicts
    # with a hardware/compute that is NOT their own host chain.
    for svc in svc_objs:
        own_ip = _norm(svc.ip_address)
        if not own_ip or _parse_ports_json(svc.ports_json):
            continue
        # Build the set of host IDs that are allowed to share this IP
        allowed_hw: set[int] = set()
        allowed_cu: set[int] = set()
        if svc.compute_id:
            allowed_cu.add(svc.compute_id)
            hw_id = cu_id_to_hw_id.get(svc.compute_id)  # type: ignore[assignment]
            if hw_id:
                allowed_hw.add(hw_id)
        if svc.hardware_id:
            allowed_hw.add(svc.hardware_id)
        conflicting_hws = [hid for hid in ip_to_hw.get(own_ip, []) if hid not in allowed_hw]
        conflicting_cus = [cid for cid in ip_to_cu.get(own_ip, []) if cid not in allowed_cu]
        if conflicting_hws or conflicting_cus:
            result[("service", svc.id)] = True

    return result


# ── IPAM reservation & conflict management ─────────────────────────────────


def auto_reserve_ip(
    db: Session,
    hardware_id: int,
    ip_address: str,
    hostname: str | None,
    tenant_id: int | None = None,
) -> IPAddress | None:
    """Auto-reserve an IP for a hardware node.

    Returns the IPAddress row on success, or None if there is a conflict
    (IP owned by a different hardware node).
    """
    existing = db.execute(
        select(IPAddress).where(
            IPAddress.address == ip_address,
            *([IPAddress.tenant_id == tenant_id] if tenant_id is not None else []),
        )
    ).scalar_one_or_none()

    if existing:
        if existing.hardware_id is not None and existing.hardware_id != hardware_id:
            return None  # conflict — owned by different hardware
        # Same hardware owns it already — just update hostname
        existing.hostname = hostname
        existing.hardware_id = hardware_id
        existing.status = "allocated"
        db.flush()
        return existing

    # New reservation
    # Find matching network via subnet
    network_id: int | None = None
    try:
        parsed_ip = _ipaddress.ip_address(ip_address)
        for net in db.execute(select(Network)).scalars().all():
            if net.cidr:
                try:
                    if parsed_ip in _ipaddress.ip_network(net.cidr, strict=False):
                        network_id = net.id
                        break
                except ValueError:
                    continue
    except ValueError:
        pass

    row = IPAddress(
        address=ip_address,
        hardware_id=hardware_id,
        hostname=hostname,
        status="allocated",
        network_id=network_id,
        tenant_id=tenant_id,
        allocated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def release_hardware_ips(db: Session, hardware_id: int) -> int:
    """Release all IP reservations for a hardware node.

    Sets status to 'free' and clears hardware_id.
    Returns the count of freed IPs.
    """
    rows = db.execute(select(IPAddress).where(IPAddress.hardware_id == hardware_id)).scalars().all()
    for row in rows:
        row.status = "free"
        row.hardware_id = None
    db.flush()
    return len(rows)


def record_conflict(
    db: Session,
    address: str,
    entity_a_type: str,
    entity_a_id: int,
    entity_b_type: str,
    entity_b_id: int,
    conflict_type: str = "ip_overlap",
    port: int | None = None,
    protocol: str | None = None,
    tenant_id: int | None = None,
) -> IPConflict:
    """Record an IP conflict (idempotent — returns existing open conflict if present)."""
    from sqlalchemy import or_

    # Check for existing open conflict for same address + entity pair (either order)
    existing = db.execute(
        select(IPConflict).where(
            IPConflict.address == address,
            IPConflict.status == "open",
            or_(
                (IPConflict.entity_a_type == entity_a_type)
                & (IPConflict.entity_a_id == entity_a_id)
                & (IPConflict.entity_b_type == entity_b_type)
                & (IPConflict.entity_b_id == entity_b_id),
                (IPConflict.entity_a_type == entity_b_type)
                & (IPConflict.entity_a_id == entity_b_id)
                & (IPConflict.entity_b_type == entity_a_type)
                & (IPConflict.entity_b_id == entity_a_id),
            ),
        )
    ).scalar_one_or_none()

    if existing:
        return existing

    conflict = IPConflict(
        address=address,
        entity_a_type=entity_a_type,
        entity_a_id=entity_a_id,
        entity_b_type=entity_b_type,
        entity_b_id=entity_b_id,
        conflict_type=conflict_type,
        port=port,
        protocol=protocol,
        status="open",
        tenant_id=tenant_id,
    )
    db.add(conflict)
    db.flush()
    return conflict


def resolve_conflict(
    db: Session,
    conflict_id: int,
    resolution: str,
    user_id: int | None = None,
    notes: str | None = None,
) -> IPConflict:
    """Resolve an IP conflict with the given resolution strategy.

    resolution can be:
    - "reassign": reassign the IP to entity_b (if hardware)
    - "keep_existing": no data change, just mark resolved
    - "free_and_assign": free existing IP, create new for entity_b
    """
    conflict = db.get(IPConflict, conflict_id)
    if not conflict:
        raise ValueError(f"IPConflict {conflict_id} not found")

    conflict.resolution = resolution
    conflict.resolved_by = user_id
    conflict.resolved_at = utcnow()
    conflict.status = "resolved"
    conflict.notes = notes

    # Execute resolution
    if resolution == "reassign":
        ip_row = db.execute(
            select(IPAddress).where(IPAddress.address == conflict.address)
        ).scalar_one_or_none()
        if ip_row and conflict.entity_b_type == "hardware":
            ip_row.hardware_id = conflict.entity_b_id
    elif resolution == "keep_existing":
        pass  # No data change
    elif resolution == "free_and_assign":
        ip_row = db.execute(
            select(IPAddress).where(IPAddress.address == conflict.address)
        ).scalar_one_or_none()
        if ip_row:
            ip_row.status = "free"
            ip_row.hardware_id = None
        if conflict.entity_b_type == "hardware":
            new_ip = IPAddress(
                address=conflict.address,
                hardware_id=conflict.entity_b_id,
                status="allocated",
                allocated_at=utcnow(),
                tenant_id=conflict.tenant_id,
            )
            db.add(new_ip)

    db.flush()
    return conflict


def list_open_conflicts(db: Session, tenant_id: int | None = None) -> list[IPConflict]:
    """Return all open IP conflicts, optionally filtered by tenant."""
    q = select(IPConflict).where(IPConflict.status == "open")
    if tenant_id is not None:
        q = q.where(IPConflict.tenant_id == tenant_id)
    return list(db.execute(q).scalars().all())
