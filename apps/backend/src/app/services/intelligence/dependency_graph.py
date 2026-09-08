"""Bounded, explainable potential-impact traversal over operational dependencies."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.db.models import ComputeUnit, Hardware, Service, Storage
from app.services.intelligence.dependency_edges import (
    AssetKey,
    DependencyEdge,
    build_impact_adjacency,
    load_dependency_edges,
)

VALID_ASSET_TYPES = frozenset({"hardware", "compute_unit", "service", "storage"})
DEFAULT_MAX_NODES = 500
DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_EDGES = 5000

_AssetModel = type[Hardware] | type[ComputeUnit] | type[Service] | type[Storage]
_MODEL_MAP: dict[str, _AssetModel] = {
    "hardware": Hardware,
    "compute_unit": ComputeUnit,
    "service": Service,
    "storage": Storage,
}


@dataclass(frozen=True)
class AssetRef:
    asset_type: str
    asset_id: int
    name: str
    status: str | None = None


@dataclass(frozen=True)
class ImpactPath:
    asset: AssetRef
    edges: list[DependencyEdge]
    provenance: str


@dataclass(frozen=True)
class ImpactLimits:
    max_nodes: int
    max_depth: int
    max_edges: int


@dataclass
class BlastRadiusResult:
    root_asset: AssetRef
    impacted_hardware: list[AssetRef] = field(default_factory=list)
    impacted_compute_units: list[AssetRef] = field(default_factory=list)
    impacted_services: list[AssetRef] = field(default_factory=list)
    impacted_storage: list[AssetRef] = field(default_factory=list)
    total_impact_count: int = 0
    summary: str = ""
    paths: list[ImpactPath] = field(default_factory=list)
    edges: list[DependencyEdge] = field(default_factory=list)
    connectivity: list[DependencyEdge] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=utcnow)
    completeness: str = "complete"
    truncation_reason: str | None = None
    limits: ImpactLimits = field(
        default_factory=lambda: ImpactLimits(
            DEFAULT_MAX_NODES, DEFAULT_MAX_DEPTH, DEFAULT_MAX_EDGES
        )
    )
    inferred_available: bool = False


def _build_adjacency(db: Session) -> dict[AssetKey, list[AssetKey]]:
    """Compatibility view of confirmed operational edges only."""
    edge_set = load_dependency_edges(db)
    return {
        provider: [edge.dependent for edge in edges]
        for provider, edges in build_impact_adjacency(edge_set.dependencies).items()
    }


def _resolve_many(db: Session, keys: set[AssetKey]) -> dict[AssetKey, AssetRef]:
    grouped: dict[str, set[int]] = {}
    for asset_type, asset_id in keys:
        if asset_type in _MODEL_MAP:
            grouped.setdefault(asset_type, set()).add(asset_id)
    resolved: dict[AssetKey, AssetRef] = {}
    for asset_type, ids in grouped.items():
        model: Any = _MODEL_MAP[asset_type]
        for obj in db.query(model).filter(model.id.in_(ids)).all():
            status = getattr(obj, "status", None) or getattr(obj, "telemetry_status", None)
            resolved[(asset_type, obj.id)] = AssetRef(
                asset_type=asset_type,
                asset_id=obj.id,
                name=obj.name,
                status=status,
            )
    return resolved


def _path_for(
    key: AssetKey,
    root: AssetKey,
    predecessor: dict[AssetKey, DependencyEdge],
) -> list[DependencyEdge]:
    path: list[DependencyEdge] = []
    current = key
    while current != root:
        edge = predecessor.get(current)
        if edge is None:
            break
        path.append(edge)
        current = edge.provider
    path.reverse()
    return path


def calculate_blast_radius(
    db: Session,
    asset_type: str,
    asset_id: int,
    *,
    include_inferred: bool = False,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> BlastRadiusResult:
    """Return deterministic potential impact with one evidence path per asset."""
    if asset_type not in VALID_ASSET_TYPES:
        raise ValueError(f"Unknown asset_type: {asset_type!r}")
    if min(max_nodes, max_depth, max_edges) < 1:
        raise ValueError("Impact traversal limits must be positive")

    root_key = (asset_type, asset_id)
    root_resolved = _resolve_many(db, {root_key}).get(root_key)
    if root_resolved is None:
        raise NotFoundError("Asset not found.")

    edge_set = load_dependency_edges(db)
    adjacency = build_impact_adjacency(edge_set.dependencies, include_inferred=include_inferred)
    visited: set[AssetKey] = {root_key}
    predecessor: dict[AssetKey, DependencyEdge] = {}
    depth_by_key: dict[AssetKey, int] = {root_key: 0}
    queue: deque[AssetKey] = deque([root_key])
    used_edges: list[DependencyEdge] = []
    truncation_reason: str | None = None
    examined_edges = 0

    while queue and truncation_reason is None:
        provider = queue.popleft()
        depth = depth_by_key[provider]
        outgoing = adjacency.get(provider, [])
        if depth >= max_depth and outgoing:
            truncation_reason = "depth_limit"
            break
        for edge in outgoing:
            examined_edges += 1
            if examined_edges > max_edges:
                truncation_reason = "edge_limit"
                break
            dependent = edge.dependent
            if dependent in visited:
                continue
            if len(visited) - 1 >= max_nodes:
                truncation_reason = "node_limit"
                break
            visited.add(dependent)
            predecessor[dependent] = edge
            depth_by_key[dependent] = depth + 1
            used_edges.append(edge)
            queue.append(dependent)

    impacted_keys = visited - {root_key}
    refs = _resolve_many(db, impacted_keys)
    impacted = sorted(refs.values(), key=lambda ref: (ref.asset_type, ref.asset_id))
    result = BlastRadiusResult(
        root_asset=root_resolved,
        impacted_hardware=[ref for ref in impacted if ref.asset_type == "hardware"],
        impacted_compute_units=[ref for ref in impacted if ref.asset_type == "compute_unit"],
        impacted_services=[ref for ref in impacted if ref.asset_type == "service"],
        impacted_storage=[ref for ref in impacted if ref.asset_type == "storage"],
        total_impact_count=len(impacted),
        edges=[edge for edge in used_edges if edge.dependent in refs],
        evaluated_at=utcnow(),
        completeness="truncated" if truncation_reason else "complete",
        truncation_reason=truncation_reason,
        limits=ImpactLimits(max_nodes, max_depth, max_edges),
        inferred_available=any(edge.provenance == "inferred" for edge in edge_set.dependencies),
    )
    affected_keys = set(refs) | {root_key}
    result.connectivity = [
        edge
        for edge in edge_set.connectivity
        if edge.provider in affected_keys or edge.dependent in affected_keys
    ]
    for ref in impacted:
        path = _path_for((ref.asset_type, ref.asset_id), root_key, predecessor)
        result.paths.append(
            ImpactPath(
                asset=ref,
                edges=path,
                provenance=(
                    "inferred"
                    if any(edge.provenance == "inferred" for edge in path)
                    else "confirmed"
                ),
            )
        )

    parts: list[str] = []
    for label, refs_for_type in (
        ("VM", result.impacted_compute_units),
        ("service", result.impacted_services),
        ("downstream device", result.impacted_hardware),
        ("storage item", result.impacted_storage),
    ):
        if refs_for_type:
            count = len(refs_for_type)
            parts.append(f"{count} {label}{'s' if count != 1 else ''}")
    suffix = " Results are truncated." if truncation_reason else ""
    result.summary = (
        f"Potential impact if {root_resolved.name} is unavailable: "
        f"{', '.join(parts)} affected.{suffix}"
        if parts
        else (f"No confirmed downstream dependencies were found for {root_resolved.name}.{suffix}")
    )
    return result
