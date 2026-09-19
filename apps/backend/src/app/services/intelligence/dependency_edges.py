"""Load and classify operational dependency evidence from existing relations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import (
    ComputeNetwork,
    ComputeUnit,
    HardwareConnection,
    HardwareNetwork,
    Service,
    ServiceDependency,
    ServiceStorage,
    Storage,
)

AssetKey = tuple[str, int]
EdgeType = Literal["hosting", "dependency", "connectivity", "inferred_dependency"]
Provenance = Literal["confirmed", "inferred"]


@dataclass(frozen=True)
class DependencyEdge:
    """Provider → dependent evidence used for outage-impact traversal."""

    provider: AssetKey
    dependent: AssetKey
    edge_type: EdgeType
    source_kind: str
    source_id: int
    provenance: Provenance = "confirmed"
    label: str | None = None

    @property
    def identity(self) -> str:
        return (
            f"{self.source_kind}:{self.source_id}:"
            f"{self.provider[0]}:{self.provider[1]}:"
            f"{self.dependent[0]}:{self.dependent[1]}"
        )


@dataclass
class EdgeSet:
    dependencies: list[DependencyEdge] = field(default_factory=list)
    connectivity: list[DependencyEdge] = field(default_factory=list)


def load_dependency_edges(db: Session) -> EdgeSet:
    """Load bounded relationship classes without expanding shared networks."""
    result = EdgeSet()
    for compute in db.query(ComputeUnit.id, ComputeUnit.hardware_id).all():
        if compute.hardware_id is not None:
            result.dependencies.append(
                DependencyEdge(
                    ("hardware", compute.hardware_id),
                    ("compute_unit", compute.id),
                    "hosting",
                    "compute_units.hardware_id",
                    compute.id,
                    label="hosted by",
                )
            )
    for service in db.query(Service.id, Service.hardware_id, Service.compute_id).all():
        if service.hardware_id is not None:
            result.dependencies.append(
                DependencyEdge(
                    ("hardware", service.hardware_id),
                    ("service", service.id),
                    "hosting",
                    "services.hardware_id",
                    service.id,
                    label="runs on",
                )
            )
        if service.compute_id is not None:
            result.dependencies.append(
                DependencyEdge(
                    ("compute_unit", service.compute_id),
                    ("service", service.id),
                    "hosting",
                    "services.compute_id",
                    service.id,
                    label="runs on",
                )
            )
    for dependency in db.query(ServiceDependency).all():
        result.dependencies.append(
            DependencyEdge(
                ("service", dependency.depends_on_id),
                ("service", dependency.service_id),
                "dependency",
                "service_dependencies",
                dependency.id,
                label=dependency.connection_type or "depends on",
            )
        )
    for storage in db.query(Storage.id, Storage.hardware_id).all():
        if storage.hardware_id is not None:
            result.dependencies.append(
                DependencyEdge(
                    ("hardware", storage.hardware_id),
                    ("storage", storage.id),
                    "hosting",
                    "storage.hardware_id",
                    storage.id,
                    label="hosted by",
                )
            )
    for storage_link in db.query(ServiceStorage).all():
        result.dependencies.append(
            DependencyEdge(
                ("storage", storage_link.storage_id),
                ("service", storage_link.service_id),
                "dependency",
                "service_storage",
                storage_link.id,
                label=storage_link.purpose or storage_link.connection_type or "uses storage",
            )
        )

    # Physical links and memberships are useful context, never operational
    # propagation evidence by themselves. Membership rows remain O(n): there
    # is deliberately no pairwise subnet expansion here.
    for connection in db.query(HardwareConnection).all():
        result.connectivity.append(
            DependencyEdge(
                ("hardware", connection.source_hardware_id),
                ("hardware", connection.target_hardware_id),
                "connectivity",
                "hardware_connections",
                connection.id,
                label=connection.connection_type,
            )
        )
    for hardware_network in db.query(HardwareNetwork).all():
        result.connectivity.append(
            DependencyEdge(
                ("network", hardware_network.network_id),
                ("hardware", hardware_network.hardware_id),
                "connectivity",
                "hardware_networks",
                hardware_network.id,
                label="network membership",
            )
        )
    for compute_network in db.query(ComputeNetwork).all():
        result.connectivity.append(
            DependencyEdge(
                ("network", compute_network.network_id),
                ("compute_unit", compute_network.compute_id),
                "connectivity",
                "compute_networks",
                compute_network.id,
                label="network membership",
            )
        )
    result.dependencies.sort(key=lambda edge: edge.identity)
    result.connectivity.sort(key=lambda edge: edge.identity)
    return result


def build_impact_adjacency(
    edges: list[DependencyEdge], *, include_inferred: bool = False
) -> dict[AssetKey, list[DependencyEdge]]:
    adjacency: dict[AssetKey, list[DependencyEdge]] = {}
    seen: set[str] = set()
    for edge in edges:
        if edge.edge_type == "connectivity":
            continue
        if edge.provenance == "inferred" and not include_inferred:
            continue
        if edge.identity in seen:
            continue
        seen.add(edge.identity)
        adjacency.setdefault(edge.provider, []).append(edge)
    for values in adjacency.values():
        values.sort(key=lambda edge: (edge.dependent, edge.identity))
    return adjacency
