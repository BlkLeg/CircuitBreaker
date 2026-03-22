"""Blast-radius traversal: given an asset going offline, find all downstream impacted entities.

Graph edges loaded from:
  - HardwareConnection: source_hardware_id → target_hardware_id
  - HardwareNetwork: hw ↔ hw through shared network membership (bidirectional)
  - ComputeUnit.hardware_id: hardware → compute_unit (CU is downstream of its host)
  - Service.hardware_id / Service.compute_id: parent → service
  - ServiceDependency(service_id depends_on depends_on_id): if A depends on B, B→A edge
  - Storage.hardware_id: hardware → storage
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import (
    ComputeUnit,
    Hardware,
    HardwareConnection,
    HardwareNetwork,
    Service,
    ServiceDependency,
    Storage,
)

_logger = logging.getLogger(__name__)

VALID_ASSET_TYPES = frozenset({"hardware", "compute_unit", "service", "storage"})
_MODEL_MAP = {
    "hardware": Hardware,
    "compute_unit": ComputeUnit,
    "service": Service,
    "storage": Storage,
}


@dataclass
class AssetRef:
    asset_type: str
    asset_id: int
    name: str
    status: str | None = None


@dataclass
class BlastRadiusResult:
    root_asset: AssetRef
    impacted_hardware: list[AssetRef] = field(default_factory=list)
    impacted_compute_units: list[AssetRef] = field(default_factory=list)
    impacted_services: list[AssetRef] = field(default_factory=list)
    impacted_storage: list[AssetRef] = field(default_factory=list)
    total_impact_count: int = 0
    summary: str = ""


def _build_adjacency(db: Session) -> dict[tuple[str, int], list[tuple[str, int]]]:
    adj: dict[tuple[str, int], list[tuple[str, int]]] = {}

    def _add(src: tuple[str, int], dst: tuple[str, int]) -> None:
        adj.setdefault(src, []).append(dst)

    # Direct hardware-to-hardware connections
    for row in db.query(HardwareConnection).all():
        _add(("hardware", row.source_hardware_id), ("hardware", row.target_hardware_id))

    # Hardware through shared network membership (bidirectional)
    net_hw: dict[int, list[int]] = {}
    for row in db.query(HardwareNetwork).all():
        net_hw.setdefault(row.network_id, []).append(row.hardware_id)
    for hw_ids in net_hw.values():
        for i, src in enumerate(hw_ids):
            for dst in hw_ids[i + 1 :]:
                _add(("hardware", src), ("hardware", dst))
                _add(("hardware", dst), ("hardware", src))

    # Compute units hosted on hardware
    for cu in db.query(ComputeUnit).filter(ComputeUnit.hardware_id.isnot(None)).all():
        _add(("hardware", cu.hardware_id), ("compute_unit", cu.id))

    # Services running on hardware or compute units
    for svc in db.query(Service).all():
        if svc.hardware_id:
            _add(("hardware", svc.hardware_id), ("service", svc.id))
        if svc.compute_id:
            _add(("compute_unit", svc.compute_id), ("service", svc.id))

    # Service dependencies: if B goes down, all services that depend on B are impacted
    for dep in db.query(ServiceDependency).all():
        _add(("service", dep.depends_on_id), ("service", dep.service_id))

    # Storage attached to hardware
    for st in db.query(Storage).filter(Storage.hardware_id.isnot(None)).all():
        _add(("hardware", st.hardware_id), ("storage", st.id))

    return adj


def _resolve(db: Session, asset_type: str, asset_id: int) -> tuple[str, str | None]:
    obj = db.get(_MODEL_MAP[asset_type], asset_id)
    if obj is None:
        return f"{asset_type}:{asset_id}", None
    name = getattr(obj, "name", str(asset_id))
    status = getattr(obj, "status", None) or getattr(obj, "telemetry_status", None)
    return name, status


def calculate_blast_radius(db: Session, asset_type: str, asset_id: int) -> BlastRadiusResult:
    """BFS from (asset_type, asset_id) to find all downstream impacted entities."""
    if asset_type not in VALID_ASSET_TYPES:
        raise ValueError(f"Unknown asset_type: {asset_type!r}")

    adj = _build_adjacency(db)
    root_name, root_status = _resolve(db, asset_type, asset_id)
    root = AssetRef(asset_type=asset_type, asset_id=asset_id, name=root_name, status=root_status)
    result = BlastRadiusResult(root_asset=root)

    visited: set[tuple[str, int]] = {(asset_type, asset_id)}
    queue: deque[tuple[str, int]] = deque(adj.get((asset_type, asset_id), []))

    while queue:
        key = queue.popleft()
        if key in visited:
            continue
        visited.add(key)
        atype, aid = key
        name, status = _resolve(db, atype, aid)
        ref = AssetRef(asset_type=atype, asset_id=aid, name=name, status=status)
        if atype == "hardware":
            result.impacted_hardware.append(ref)
        elif atype == "compute_unit":
            result.impacted_compute_units.append(ref)
        elif atype == "service":
            result.impacted_services.append(ref)
        elif atype == "storage":
            result.impacted_storage.append(ref)
        for neighbor in adj.get(key, []):
            if neighbor not in visited:
                queue.append(neighbor)

    result.total_impact_count = (
        len(result.impacted_hardware)
        + len(result.impacted_compute_units)
        + len(result.impacted_services)
        + len(result.impacted_storage)
    )

    parts: list[str] = []
    if result.impacted_compute_units:
        n = len(result.impacted_compute_units)
        parts.append(f"{n} VM{'s' if n != 1 else ''}")
    if result.impacted_services:
        n = len(result.impacted_services)
        parts.append(f"{n} service{'s' if n != 1 else ''}")
    if result.impacted_hardware:
        n = len(result.impacted_hardware)
        parts.append(f"{n} downstream device{'s' if n != 1 else ''}")

    result.summary = (
        f"{root_name} is DOWN. Impact: {', '.join(parts)} affected."
        if parts
        else f"{root_name} is DOWN. No downstream dependencies detected."
    )
    return result
