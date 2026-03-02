"""IP/port conflict detection across hardware, compute units, and services."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Hardware, ComputeUnit, Service

_logger = logging.getLogger(__name__)


@dataclass
class ConflictResult:
    entity_type: str           # "hardware" | "compute_unit" | "service"
    entity_id: int
    entity_name: str
    conflicting_ip: str
    conflicting_port: Optional[int]
    protocol: Optional[str]

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


def _parse_ports_json(raw: str | None) -> list[dict]:
    """Return the parsed port-entry list from a ports_json TEXT column value."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
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
            conflicts.append(ConflictResult(
                entity_type="hardware",
                entity_id=hw.id,
                entity_name=hw.name,
                conflicting_ip=norm_ip,
                conflicting_port=None,
                protocol=None,
            ))

    for cu in db.execute(select(ComputeUnit)).scalars().all():
        if _is_self("compute_unit", cu.id):
            continue
        if _norm(cu.ip_address) == norm_ip:
            conflicts.append(ConflictResult(
                entity_type="compute_unit",
                entity_id=cu.id,
                entity_name=cu.name,
                conflicting_ip=norm_ip,
                conflicting_port=None,
                protocol=None,
            ))

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
                conflicts.append(ConflictResult(
                    entity_type="service",
                    entity_id=svc.id,
                    entity_name=svc.name,
                    conflicting_ip=effective_ip,
                    conflicting_port=pe_port,
                    protocol=pe_proto,
                ))

        # Rule 3: portless service on the same IP as a hardware/compute node
        # Only applies when the incoming entity is hardware or compute_unit (not a service)
        if (
            exclude_entity_type in ("hardware", "compute_unit")
            and svc_ip == norm_ip
            and not svc_ports
        ):
            conflicts.append(ConflictResult(
                entity_type="service",
                entity_id=svc.id,
                entity_name=svc.name,
                conflicting_ip=norm_ip,
                conflicting_port=None,
                protocol=None,
            ))

    return conflicts


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

    def _svc_effective_ip(svc: "Service") -> str | None:
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
                binding_to_svc[(eff_ip, int(pe["port"]), (pe.get("protocol") or "tcp").lower())].append(svc_id)

    # Hardware conflicts: multiple hardware on same IP
    for hw_id, _, hw_ip in hw_rows:
        if hw_ip and len(ip_to_hw[hw_ip]) > 1:
            result[("hardware", hw_id)] = True

    # Compute conflicts: multiple compute on same IP
    for cu_id, _, cu_ip in cu_rows:
        if cu_ip and len(ip_to_cu[cu_ip]) > 1:
            result[("compute_unit", cu_id)] = True

    # Service conflicts: duplicate (ip, port, protocol) bindings
    for binding, svc_ids in binding_to_svc.items():
        if len(svc_ids) > 1:
            for sid in svc_ids:
                result[("service", sid)] = True

    # Portless services on an IP that also belongs to a hardware/compute node
    for svc_id, _, svc_eff_ip, svc_ports in svc_rows:
        if svc_eff_ip and not svc_ports and (svc_eff_ip in ip_to_hw or svc_eff_ip in ip_to_cu):
            result[("service", svc_id)] = True

    return result
