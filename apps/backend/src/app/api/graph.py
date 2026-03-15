import hashlib
import json
import logging
from typing import Any, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.rbac import require_scope
from app.core.security import require_write_auth
from app.db.models import (
    ComputeNetwork,
    ComputeUnit,
    Doc,
    EntityDoc,
    EntityTag,
    ExternalNode,
    ExternalNodeNetwork,
    GraphLayout,
    Hardware,
    HardwareCluster,
    HardwareClusterMember,
    HardwareConnection,
    HardwareMonitor,
    HardwareNetwork,
    MiscItem,
    Network,
    NetworkPeer,
    Rack,
    Service,
    ServiceDependency,
    ServiceExternalNode,
    ServiceMisc,
    ServiceStorage,
    Storage,
    Tag,
)
from app.db.session import get_db
from app.services.ip_reservation import bulk_conflict_map

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["graph"], dependencies=[require_scope("read", "*")])


class TopologyContext(TypedDict):
    """Shared context for topology graph building to avoid passing many parameters."""

    db: Session
    include_set: set[str]
    conflict_map: dict[tuple[str, int], bool]
    entity_tags_map: dict[tuple[str, int], list[str]]
    entity_docs_map: dict[tuple[str, int], list[dict]]
    cu_storage_pools: dict[int, list[str]]
    cu_networks: dict[int, list[int]]
    hw_networks: dict[int, list[int]]
    environment: str | None
    environment_id: int | None
    rack_id: int | None


def _preload_edge_maps(db: Session) -> dict:
    """CTE-based bulk preload of all edge/relation data in a single round-trip.

    Returns a dict of pre-built lookup maps that build_topology_graph uses
    to emit edges without issuing separate queries for each join table.
    """
    from sqlalchemy import text as _text

    # Fetch all relationship data via a single UNION ALL CTE.
    # Each row: (edge_type, source_type, source_id, target_type, target_id,
    #            connection_type, bandwidth_mbps, row_id)
    cte_sql = _text("""
        WITH all_edges AS (
            SELECT 'hn' AS edge_type,
                   hardware_id AS src_id, network_id AS tgt_id,
                   connection_type, bandwidth_mbps, id AS row_id
            FROM hardware_networks
          UNION ALL
            SELECT 'cn', compute_id, network_id,
                   connection_type, bandwidth_mbps, id
            FROM compute_networks
          UNION ALL
            SELECT 'hh', source_hardware_id, target_hardware_id,
                   connection_type, bandwidth_mbps, id
            FROM hardware_connections
          UNION ALL
            SELECT 'np', network_a_id, network_b_id,
                   NULL, NULL, 0
            FROM network_peers
          UNION ALL
            SELECT 'dep', service_id, depends_on_id,
                   connection_type, bandwidth_mbps, id
            FROM service_dependencies
          UNION ALL
            SELECT 'ss', service_id, storage_id,
                   connection_type, bandwidth_mbps, id
            FROM service_storage
          UNION ALL
            SELECT 'sm', service_id, misc_id,
                   connection_type, bandwidth_mbps, id
            FROM service_misc
          UNION ALL
            SELECT 'extnet', external_node_id, network_id,
                   connection_type, bandwidth_mbps, id
            FROM external_node_networks
          UNION ALL
            SELECT 'svcext', service_id, external_node_id,
                   connection_type, bandwidth_mbps, id
            FROM service_external_nodes
          UNION ALL
            SELECT 'hcm', cluster_id, hardware_id,
                   NULL, NULL, id
            FROM hardware_cluster_members
        )
        SELECT edge_type, src_id, tgt_id, connection_type, bandwidth_mbps, row_id
        FROM all_edges
    """)

    result: dict[str, list] = {}
    try:
        rows = db.execute(cte_sql).all()
        for edge_type, src_id, tgt_id, conn_type, bw, row_id in rows:
            result.setdefault(edge_type, []).append((src_id, tgt_id, conn_type, bw, row_id))
    except Exception:
        _logger.debug("CTE edge preload failed; falling back to per-table queries")
    return result


_ALLOWED_CONNECTION_TYPES = {"ethernet", "wireless", "tunnel", "wg", "vpn", "ssh"}
_CONNECTION_TYPE_ALIASES = {"wireguard": "wg"}


def _normalize_connection_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _CONNECTION_TYPE_ALIASES.get(value.strip().lower(), value.strip().lower())
    if normalized not in _ALLOWED_CONNECTION_TYPES:
        raise ValueError(f"Unsupported connection_type '{value}'")
    return normalized


# ── v2 edge helper ───────────────────────────────────────────────────────────


def build_edge_dict(
    id: str,
    source: str,
    target: str,
    relation: str,
    connection_type: str | None = None,
    bandwidth_mbps: int | None = None,
) -> dict:
    """Build a topology edge dict with optional v2 connection metadata."""
    normalized_type = None
    if connection_type:
        try:
            normalized_type = _normalize_connection_type(connection_type)
        except ValueError:
            _logger.warning(
                "Ignoring unsupported connection_type '%s' on edge %s", connection_type, id
            )
    data: dict[str, Any] = {"relation": relation}
    if normalized_type is not None:
        data["connection_type"] = normalized_type
    if bandwidth_mbps is not None:
        data["bandwidth"] = bandwidth_mbps
        data["label"] = f"{bandwidth_mbps}Mbps"
    elif normalized_type is not None:
        data["bandwidth"] = 1000

    return {
        "id": id,
        "source": source,
        "target": target,
        "relation": relation,
        "type": "custom",
        "data": data,
    }


# ── Edge mutation helpers ────────────────────────────────────────────────────

# Ordered list of deletable edge prefixes → SQLAlchemy model
# Multi-word prefixes must precede shorter ones to avoid false matches.
_DELETABLE_EDGES = [
    ("e-ext-net-", ExternalNodeNetwork),
    ("e-svc-ext-", ServiceExternalNode),
    ("e-dep-", ServiceDependency),
    ("e-ss-", ServiceStorage),
    ("e-sm-", ServiceMisc),
    ("e-cn-", ComputeNetwork),
    ("e-hn-", HardwareNetwork),
    ("e-hh-", HardwareConnection),
]


def _parse_deletable_edge(edge_id: str):
    """Return (model_class, row_id) for deletable/updatable edges, else (None, None)."""
    for prefix, model in _DELETABLE_EDGES:
        if edge_id.startswith(prefix):
            try:
                return model, int(edge_id[len(prefix) :])
            except ValueError:
                return None, None
    return None, None


class EdgeUpdatePayload(BaseModel):
    connection_type: str


@router.delete("/edges/{edge_id}", status_code=204)
def delete_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Delete a topology edge (connection join-table row) by its React Flow edge ID.

    Structural edges (hosts, runs, rack_member, cluster_member, etc.) and
    implicit derived edges return 400 — they must be managed via their
    respective entity endpoints.
    """
    model, row_id = _parse_deletable_edge(edge_id)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail=f"Edge '{edge_id}' is structural or implicit and cannot be deleted here.",
        )
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    db.delete(row)
    db.commit()


@router.patch("/edges/{edge_id}", status_code=200)
def update_edge_type(
    edge_id: str,
    payload: EdgeUpdatePayload,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Update the connection_type on a topology edge."""
    model, row_id = _parse_deletable_edge(edge_id)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail=f"Edge '{edge_id}' is not updatable here.",
        )
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    try:
        normalized = _normalize_connection_type(payload.connection_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if hasattr(row, "connection_type"):
        row.connection_type = normalized
        db.commit()
    return {"status": "ok", "connection_type": normalized}


class LayoutUpdate(BaseModel):
    name: str = "default"
    layout_data: str  # JSON string
    constraints: dict = Field(default_factory=dict)


class PlaceNodeInput(BaseModel):
    node_id: str
    environment: str = "default"


def _get_tags(ctx: TopologyContext, entity_type: str, entity_id: int) -> list[str]:
    """Retrieve tags for an entity from the pre-computed context map."""
    return ctx["entity_tags_map"].get((entity_type, entity_id), [])


def _get_docs(ctx: TopologyContext, entity_type: str, entity_id: int) -> list[dict]:
    """Retrieve docs for an entity from the pre-computed context map."""
    return ctx["entity_docs_map"].get((entity_type, entity_id), [])


def _process_storage(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process storage entities and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "storage" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]

    proxmox_hw_lookup: dict[tuple[int, str], Hardware] = {}
    for hw in db.execute(select(Hardware)).scalars():
        if hw.integration_config_id and hw.proxmox_node_name:
            proxmox_hw_lookup[(hw.integration_config_id, hw.proxmox_node_name.strip())] = hw

    for st in db.execute(select(Storage).options(joinedload(Storage.hardware))).unique().scalars():
        inferred_hw_id = st.hardware_id
        inferred_vendor = st.hardware.vendor if st.hardware else None
        inferred_icon = st.hardware.vendor_icon_slug if st.hardware else None

        if inferred_hw_id is None and st.integration_config_id and st.name and "@" in st.name:
            node_name = st.name.rsplit("@", 1)[-1].strip()
            fallback_hw = proxmox_hw_lookup.get((st.integration_config_id, node_name))
            if fallback_hw is not None:
                inferred_hw_id = fallback_hw.id
                inferred_vendor = fallback_hw.vendor
                inferred_icon = fallback_hw.vendor_icon_slug

        nodes.append(
            {
                "id": f"st-{st.id}",
                "type": "storage",
                "ref_id": st.id,
                "label": st.name,
                "kind": st.kind,
                "capacity_gb": st.capacity_gb,
                "used_gb": st.used_gb,
                "vendor": inferred_vendor,
                "icon_slug": inferred_icon,
                "tags": _get_tags(ctx, "storage", st.id),
                "hardware_id": inferred_hw_id,
                "integration_config_id": st.integration_config_id,
            }
        )

        if inferred_hw_id and "hardware" in ctx["include_set"]:
            edges.append(
                build_edge_dict(
                    id=f"e-hw-st-{st.id}",
                    source=f"hw-{inferred_hw_id}",
                    target=f"st-{st.id}",
                    relation="has_storage",
                )
            )

    return nodes, edges


def _process_misc(ctx: TopologyContext) -> list[dict]:
    """Process misc items and return nodes."""
    if "misc" not in ctx["include_set"]:
        return []

    nodes: list[dict] = []
    db = ctx["db"]

    for m in db.execute(select(MiscItem)).scalars():
        nodes.append(
            {
                "id": f"misc-{m.id}",
                "type": "misc",
                "ref_id": m.id,
                "label": m.name,
                "tags": _get_tags(ctx, "misc", m.id),
            }
        )

    return nodes


def _process_external(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process external nodes and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "external" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]
    environment = ctx["environment"]

    for ext in db.execute(select(ExternalNode)).scalars():
        if environment and ext.environment and ext.environment != environment:
            continue
        nodes.append(
            {
                "id": f"ext-{ext.id}",
                "type": "external",
                "ref_id": ext.id,
                "label": f"{ext.name} ({ext.provider})" if ext.provider else ext.name,
                "icon_slug": ext.icon_slug,
                "tags": _get_tags(ctx, "external", ext.id),
                "meta": {
                    "provider": ext.provider,
                    "kind": ext.kind,
                    "region": ext.region,
                    "ip_address": ext.ip_address,
                },
            }
        )

    if "networks" in ctx["include_set"]:
        for link in db.execute(select(ExternalNodeNetwork)).scalars().all():  # type: ignore[assignment]
            edges.append(
                build_edge_dict(
                    id=f"e-ext-net-{link.id}",
                    source=f"ext-{link.external_node_id}",  # type: ignore[attr-defined]
                    target=f"net-{link.network_id}",  # type: ignore[attr-defined]
                    relation="connects_to",
                    connection_type=getattr(link, "connection_type", None),
                    bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                )
            )

    if "services" in ctx["include_set"]:
        for svc_ext in db.execute(select(ServiceExternalNode)).scalars().all():
            edges.append(
                build_edge_dict(
                    id=f"e-svc-ext-{svc_ext.id}",
                    source=f"svc-{svc_ext.service_id}",
                    target=f"ext-{svc_ext.external_node_id}",
                    relation="depends_on",
                    connection_type=getattr(svc_ext, "connection_type", None),
                    bandwidth_mbps=getattr(svc_ext, "bandwidth_mbps", None),
                )
            )

    return nodes, edges


def _process_docker(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process docker networks and containers, return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "docker" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]

    docker_nets = (
        db.execute(
            select(Network).where(Network.is_docker_network == True)  # noqa: E712
        )
        .scalars()
        .all()
    )
    docker_net_ids = {n.id for n in docker_nets}
    for dnet in docker_nets:
        nodes.append(
            {
                "id": f"net-{dnet.id}",
                "type": "docker_network",
                "ref_id": dnet.id,
                "label": dnet.name,
                "cidr": dnet.cidr,
                "icon_slug": dnet.icon_slug,
                "docker_driver": dnet.docker_driver,
                "tags": _get_tags(ctx, "networks", dnet.id),
            }
        )

    docker_svcs = (
        db.execute(
            select(Service).where(Service.is_docker_container == True)  # noqa: E712
        )
        .scalars()
        .all()
    )
    for dsvc in docker_svcs:
        nodes.append(
            {
                "id": f"svc-{dsvc.id}",
                "type": "docker_container",
                "ref_id": dsvc.id,
                "label": dsvc.name,
                "status": dsvc.status,
                "ip_address": dsvc.ip_address,
                "docker_image": dsvc.docker_image,
                "compute_id": dsvc.compute_id,
                "hardware_id": dsvc.hardware_id,
                "docker_labels": dsvc.docker_labels,
                "tags": _get_tags(ctx, "services", dsvc.id),
            }
        )

        if dsvc.compute_id and dsvc.compute_id in ctx["cu_networks"]:
            for net_id in ctx["cu_networks"][dsvc.compute_id]:
                if net_id in docker_net_ids:
                    edges.append(
                        build_edge_dict(
                            id=f"e-docker-cn-{dsvc.id}-{net_id}",
                            source=f"svc-{dsvc.id}",
                            target=f"net-{net_id}",
                            relation="on_network",
                        )
                    )
        elif dsvc.hardware_id and dsvc.hardware_id in ctx["hw_networks"]:
            for net_id in ctx["hw_networks"][dsvc.hardware_id]:
                if net_id in docker_net_ids:
                    edges.append(
                        build_edge_dict(
                            id=f"e-docker-hn-{dsvc.id}-{net_id}",
                            source=f"svc-{dsvc.id}",
                            target=f"net-{net_id}",
                            relation="on_network",
                        )
                    )

    return nodes, edges


def _build_service_node(svc: Service, ctx: TopologyContext) -> dict:
    """Build a single service node dict with IP resolution and port parsing."""
    effective_ip = (
        svc.ip_address
        or (svc.compute_unit.ip_address if svc.compute_unit else None)
        or (svc.hardware.ip_address if svc.hardware else None)
    )
    parsed_ports = []
    if svc.ports_json:
        if isinstance(svc.ports_json, list):
            parsed_ports = svc.ports_json
        elif isinstance(svc.ports_json, str):  # type: ignore[unreachable]
            try:
                maybe_ports = json.loads(svc.ports_json)
                if isinstance(maybe_ports, list):
                    parsed_ports = maybe_ports
            except Exception:
                parsed_ports = []

    return {
        "id": f"svc-{svc.id}",
        "type": "service",
        "ref_id": svc.id,
        "label": svc.name,
        "icon_slug": svc.custom_icon or svc.icon_slug,
        "ip_address": effective_ip,
        "ports": parsed_ports,
        "compute_id": svc.compute_id,
        "hardware_id": svc.hardware_id,
        "status": svc.status or "unknown",
        "status_override": None,
        "tags": _get_tags(ctx, "services", svc.id),
        "docs": _get_docs(ctx, "service", svc.id),
        "ip_conflict": bool(svc.ip_conflict),
    }


def _build_service_edges(
    services: list[Service], service_ids: set[int], ctx: TopologyContext
) -> list[dict]:
    """Build all service-related edges."""
    edges: list[dict] = []
    db = ctx["db"]

    for svc in services:
        if svc.compute_id and "compute" in ctx["include_set"]:
            edges.append(
                build_edge_dict(
                    id=f"e-cu-svc-{svc.id}",
                    source=f"cu-{svc.compute_id}",
                    target=f"svc-{svc.id}",
                    relation="runs",
                )
            )
        elif svc.hardware_id and "hardware" in ctx["include_set"]:
            edges.append(
                build_edge_dict(
                    id=f"e-hw-svc-{svc.id}",
                    source=f"hw-{svc.hardware_id}",
                    target=f"svc-{svc.id}",
                    relation="hosts",
                )
            )

        if "networks" in ctx["include_set"]:
            seen_nets: set[int] = set()
            if svc.compute_id:
                for net_id in ctx["cu_networks"].get(svc.compute_id, []):
                    if net_id not in seen_nets:
                        seen_nets.add(net_id)
                        edges.append(
                            build_edge_dict(
                                id=f"e-svc-net-{svc.id}-{net_id}",
                                source=f"svc-{svc.id}",
                                target=f"net-{net_id}",
                                relation="on_network",
                            )
                        )
            elif svc.hardware_id:
                for net_id in ctx["hw_networks"].get(svc.hardware_id, []):
                    if net_id not in seen_nets:
                        seen_nets.add(net_id)
                        edges.append(
                            build_edge_dict(
                                id=f"e-svc-net-{svc.id}-{net_id}",
                                source=f"svc-{svc.id}",
                                target=f"net-{net_id}",
                                relation="on_network",
                            )
                        )

    deps = db.execute(select(ServiceDependency)).scalars().all()
    for dep in deps:
        if dep.service_id in service_ids and dep.depends_on_id in service_ids:
            edges.append(
                build_edge_dict(
                    id=f"e-dep-{dep.id}",
                    source=f"svc-{dep.service_id}",
                    target=f"svc-{dep.depends_on_id}",
                    relation="depends_on",
                    connection_type=getattr(dep, "connection_type", None),
                    bandwidth_mbps=getattr(dep, "bandwidth_mbps", None),
                )
            )

    if "storage" in ctx["include_set"]:
        links = db.execute(select(ServiceStorage)).scalars().all()
        for link in links:
            if link.service_id in service_ids:
                edges.append(
                    build_edge_dict(
                        id=f"e-ss-{link.id}",
                        source=f"svc-{link.service_id}",
                        target=f"st-{link.storage_id}",
                        relation="uses",
                        connection_type=getattr(link, "connection_type", None),
                        bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                    )
                )

    if "misc" in ctx["include_set"]:
        links = db.execute(select(ServiceMisc)).scalars().all()  # type: ignore[assignment]
        for link in links:
            if link.service_id in service_ids:
                edges.append(
                    build_edge_dict(
                        id=f"e-sm-{link.id}",
                        source=f"svc-{link.service_id}",
                        target=f"misc-{link.misc_id}",  # type: ignore[attr-defined]
                        relation="integrates_with",
                        connection_type=getattr(link, "connection_type", None),
                        bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                    )
                )

    return edges


def _process_services(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process services and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "services" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]
    environment_id = ctx["environment_id"]
    environment = ctx["environment"]

    q = select(Service).options(  # type: ignore[assignment]
        joinedload(Service.compute_unit),
        joinedload(Service.hardware),
    )
    if environment_id is not None:
        q = q.where(Service.environment_id == environment_id)
    elif environment:
        q = q.where(Service.environment == environment)

    services: list[Service] = db.execute(q).unique().scalars().all()  # type: ignore[assignment]
    service_ids = {s.id for s in services}

    for svc in services:
        nodes.append(_build_service_node(svc, ctx))

    edges.extend(_build_service_edges(services, service_ids, ctx))

    return nodes, edges


def _process_compute(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process compute units and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "compute" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]
    environment_id = ctx["environment_id"]
    environment = ctx["environment"]

    q = select(ComputeUnit)
    if environment_id is not None:
        q = q.where(ComputeUnit.environment_id == environment_id)
    elif environment:
        q = q.where(ComputeUnit.environment == environment)

    for cu in db.execute(q).scalars():
        pools = ctx["cu_storage_pools"].get(cu.id, [])
        storage_allocated = None
        if cu.disk_gb or pools:
            storage_allocated = {
                "disk_gb": cu.disk_gb,
                "storage_pools": pools,
            }
        nodes.append(
            {
                "id": f"cu-{cu.id}",
                "type": "compute",
                "ref_id": cu.id,
                "label": cu.name,
                "kind": cu.kind,
                "icon_slug": cu.icon_slug,
                "ip_address": cu.ip_address,
                "storage_allocated": storage_allocated,
                "status": cu.status or "unknown",
                "status_override": cu.status_override or None,
                "download_speed_mbps": cu.download_speed_mbps,
                "upload_speed_mbps": cu.upload_speed_mbps,
                "tags": _get_tags(ctx, "compute", cu.id),
                "docs": _get_docs(ctx, "compute_unit", cu.id),
                "ip_conflict": ctx["conflict_map"].get(("compute_unit", cu.id), False),
                "proxmox_vmid": cu.proxmox_vmid,
                "proxmox_type": cu.proxmox_type,
                "proxmox_status": (
                    cu.proxmox_status
                    if isinstance(cu.proxmox_status, dict)
                    else (json.loads(cu.proxmox_status) if cu.proxmox_status else None)
                ),
                "hardware_id": cu.hardware_id,
                "integration_config_id": cu.integration_config_id,
            }
        )

        if "hardware" in ctx["include_set"]:
            edges.append(
                build_edge_dict(
                    id=f"e-hw-cu-{cu.id}",
                    source=f"hw-{cu.hardware_id}",
                    target=f"cu-{cu.id}",
                    relation="hosts",
                )
            )

    return nodes, edges


def _build_hardware_node(
    hw: Hardware, ctx: TopologyContext, monitor_map: dict[int, HardwareMonitor]
) -> dict:
    """Build a single hardware node dict with all metadata."""
    storage_summary = None
    if hw.storage_items:
        total_gb = sum(s.capacity_gb or 0 for s in hw.storage_items)
        used_gb = sum(s.used_gb or 0 for s in hw.storage_items)
        kinds = list(dict.fromkeys(s.kind for s in hw.storage_items if s.kind))
        primary_pool = hw.storage_items[0].name if hw.storage_items else None
        storage_summary = {
            "total_gb": total_gb,
            "used_gb": used_gb if any(s.used_gb is not None for s in hw.storage_items) else None,
            "types": kinds,
            "primary_pool": primary_pool,
            "count": len(hw.storage_items),
        }

    telemetry_data = None
    if hw.telemetry_data:
        try:
            if isinstance(hw.telemetry_data, dict):
                telemetry_data = hw.telemetry_data
            else:
                telemetry_data = json.loads(hw.telemetry_data)  # type: ignore[unreachable]
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.debug("Failed to parse telemetry_data for hardware %d: %s", hw.id, exc)

    monitor = monitor_map.get(hw.id)

    return {
        "id": f"hw-{hw.id}",
        "type": "hardware",
        "ref_id": hw.id,
        "label": hw.name,
        "vendor": hw.vendor,
        "role": hw.role or "hardware",
        "icon_slug": hw.custom_icon or hw.vendor_icon_slug,
        "ip_address": hw.ip_address,
        "storage_summary": storage_summary,
        "tags": _get_tags(ctx, "hardware", hw.id),
        "docs": _get_docs(ctx, "hardware", hw.id),
        "status": hw.status or "unknown",
        "status_override": hw.status_override or None,
        "telemetry_status": hw.telemetry_status or "unknown",
        "telemetry_data": telemetry_data,
        "telemetry_last_polled": hw.telemetry_last_polled.isoformat()
        if hw.telemetry_last_polled
        else None,
        "u_height": hw.u_height,
        "rack_unit": hw.rack_unit,
        "rack_id": hw.rack_id,
        "rack_name": hw.rack.name if hw.rack else None,
        "download_speed_mbps": hw.download_speed_mbps,
        "upload_speed_mbps": hw.upload_speed_mbps,
        "ip_conflict": ctx["conflict_map"].get(("hardware", hw.id), False),
        "monitor_status": monitor.last_status if monitor else None,
        "monitor_latency_ms": monitor.latency_ms if monitor else None,
        "monitor_last_checked_at": monitor.last_checked_at if monitor else None,
        "monitor_uptime_pct_24h": monitor.uptime_pct_24h if monitor else None,
        "proxmox_node_name": hw.proxmox_node_name,
        "integration_config_id": hw.integration_config_id,
    }


def _build_hardware_edges(
    hw_list: list[Hardware],
    ctx: TopologyContext,
    included_cluster_ids: set[int],
    hw_node_ids: set[str],
) -> list[dict]:
    """Build all hardware-related edges."""
    edges: list[dict] = []
    db = ctx["db"]

    for hw in hw_list:
        if hw.rack_id:
            edges.append(
                build_edge_dict(
                    id=f"e-rack-{hw.rack_id}-hw-{hw.id}",
                    source=f"rack-{hw.rack_id}",
                    target=f"hw-{hw.id}",
                    relation="rack_member",
                )
            )

    svc_node_ids = {f"svc-{row[0]}" for row in db.execute(select(Service.id)).all()}
    for member in db.execute(select(HardwareClusterMember)).scalars().all():
        cluster_node_id = f"cluster-{member.cluster_id}"
        if member.cluster_id not in included_cluster_ids:
            continue
        member_type = getattr(member, "member_type", "hardware") or "hardware"
        if member_type == "service" and getattr(member, "service_id", None):
            target_node_id = f"svc-{member.service_id}"
            edge_id = f"e-cluster-{member.cluster_id}-svc-{member.service_id}"
            if target_node_id in svc_node_ids:
                edges.append(
                    build_edge_dict(
                        id=edge_id,
                        source=cluster_node_id,
                        target=target_node_id,
                        relation="cluster_member",
                    )
                )
        elif member.hardware_id:
            hw_node_id = f"hw-{member.hardware_id}"
            if hw_node_id in hw_node_ids:
                edges.append(
                    build_edge_dict(
                        id=f"e-cluster-{member.cluster_id}-hw-{member.hardware_id}",
                        source=cluster_node_id,
                        target=hw_node_id,
                        relation="cluster_member",
                    )
                )

    for hconn in db.execute(select(HardwareConnection)).scalars().all():
        src_node_id = f"hw-{hconn.source_hardware_id}"
        tgt_node_id = f"hw-{hconn.target_hardware_id}"
        if src_node_id in hw_node_ids and tgt_node_id in hw_node_ids:
            edges.append(
                build_edge_dict(
                    id=f"e-hh-{hconn.id}",
                    source=src_node_id,
                    target=tgt_node_id,
                    relation="connects_to",
                    connection_type=getattr(hconn, "connection_type", None),
                    bandwidth_mbps=getattr(hconn, "bandwidth_mbps", None),
                )
            )

    return edges


def _process_hardware(
    ctx: TopologyContext, included_cluster_ids: set[int]
) -> tuple[list[dict], list[dict]]:
    """Process hardware entities and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "hardware" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]
    rack_id = ctx["rack_id"]

    hw_query = select(Hardware).options(
        selectinload(Hardware.storage_items),
        joinedload(Hardware.rack),
    )
    if rack_id is not None:
        hw_query = hw_query.where(Hardware.rack_id == rack_id)

    _all_hw = db.execute(hw_query).unique().scalars().all()
    _all_hw_ids = [hw.id for hw in _all_hw]
    _monitors = (
        (db.query(HardwareMonitor).filter(HardwareMonitor.hardware_id.in_(_all_hw_ids)).all())
        if _all_hw_ids
        else []
    )
    _monitor_map = {m.hardware_id: m for m in _monitors}

    for hw in _all_hw:
        nodes.append(_build_hardware_node(hw, ctx, _monitor_map))

    hw_node_ids = {f"hw-{hw.id}" for hw in _all_hw}
    edges.extend(_build_hardware_edges(list(_all_hw), ctx, included_cluster_ids, hw_node_ids))

    return nodes, edges


def _process_clusters_and_racks(ctx: TopologyContext) -> tuple[list[dict], set[int]]:
    """Process clusters and racks, return (nodes, included_cluster_ids)."""
    nodes: list[dict] = []
    included_cluster_ids: set[int] = set()

    if "hardware" not in ctx["include_set"]:
        return nodes, included_cluster_ids

    db = ctx["db"]
    environment = ctx["environment"]

    clusters = db.execute(select(HardwareCluster)).scalars().all()
    for cluster in clusters:
        if environment and cluster.environment and cluster.environment != environment:
            continue
        if not cluster.members:
            continue
        included_cluster_ids.add(cluster.id)
        nodes.append(
            {
                "id": f"cluster-{cluster.id}",
                "type": "cluster",
                "ref_id": cluster.id,
                "label": cluster.name,
                "icon_slug": cluster.icon_slug,
                "environment": cluster.environment,
                "member_count": len(cluster.members),
                "cluster_type": cluster.type or "manual",
                "docs": _get_docs(ctx, "hardware_cluster", cluster.id),
            }
        )

    racks = db.execute(select(Rack)).scalars().all()
    for rack in racks:
        member_count = len(rack.hardware)
        if member_count == 0:
            continue
        nodes.append(
            {
                "id": f"rack-{rack.id}",
                "type": "rack",
                "ref_id": rack.id,
                "label": rack.name,
                "height_u": rack.height_u,
                "location": rack.location,
                "member_count": member_count,
            }
        )

    return nodes, included_cluster_ids


def _process_networks(ctx: TopologyContext) -> tuple[list[dict], list[dict]]:
    """Process networks and return (nodes, edges)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    if "networks" not in ctx["include_set"]:
        return nodes, edges

    db = ctx["db"]

    for net in db.execute(select(Network)).scalars():
        nodes.append(
            {
                "id": f"net-{net.id}",
                "type": "network",
                "ref_id": net.id,
                "label": net.name,
                "cidr": net.cidr,
                "icon_slug": net.icon_slug,
                "tags": _get_tags(ctx, "networks", net.id),
            }
        )

    if "compute" in ctx["include_set"]:
        cns = db.execute(select(ComputeNetwork)).scalars().all()
        for cn in cns:
            edges.append(
                build_edge_dict(
                    id=f"e-cn-{cn.id}",
                    source=f"cu-{cn.compute_id}",
                    target=f"net-{cn.network_id}",
                    relation="connects_to",
                    connection_type=getattr(cn, "connection_type", None),
                    bandwidth_mbps=getattr(cn, "bandwidth_mbps", None),
                )
            )

    if "hardware" in ctx["include_set"]:
        for net in db.execute(
            select(Network).where(Network.gateway_hardware_id.isnot(None))
        ).scalars():
            edges.append(
                build_edge_dict(
                    id=f"e-gw-{net.id}",
                    source=f"hw-{net.gateway_hardware_id}",
                    target=f"net-{net.id}",
                    relation="routes",
                )
            )

        hns = db.execute(select(HardwareNetwork)).scalars().all()
        for hn in hns:
            edges.append(
                build_edge_dict(
                    id=f"e-hn-{hn.id}",
                    source=f"hw-{hn.hardware_id}",
                    target=f"net-{hn.network_id}",
                    relation="on_network",
                    connection_type=getattr(hn, "connection_type", None),
                    bandwidth_mbps=getattr(hn, "bandwidth_mbps", None),
                )
            )

    all_peers = db.execute(select(NetworkPeer)).scalars().all()
    for peer in all_peers:
        edges.append(
            build_edge_dict(
                id=f"e-np-{peer.network_a_id}-{peer.network_b_id}",
                source=f"net-{peer.network_a_id}",
                target=f"net-{peer.network_b_id}",
                relation="peers_with",
            )
        )

    return nodes, edges


def _build_topology_context(
    db: Session,
    environment: str | None,
    environment_id: int | None,
    rack_id: int | None,
    include: str,
) -> TopologyContext:
    """Build shared context with pre-computed maps for topology graph generation."""
    include_set = {i.strip().lower() for i in include.split(",")}

    conflict_map = bulk_conflict_map(db)

    entity_tags_map: dict[tuple[str, int], list[str]] = {}
    link_rows = db.execute(
        select(EntityTag.entity_type, EntityTag.entity_id, Tag.name).join(
            Tag, EntityTag.tag_id == Tag.id
        )
    ).all()
    for etype, eid, tname in link_rows:
        key = (etype, eid)
        if key not in entity_tags_map:
            entity_tags_map[key] = []
        entity_tags_map[key].append(tname)

    entity_docs_map: dict[tuple[str, int], list[dict]] = {}
    doc_rows = db.execute(
        select(EntityDoc.entity_type, EntityDoc.entity_id, Doc.title, Doc.id).join(
            Doc, EntityDoc.doc_id == Doc.id
        )
    ).all()
    for etype, eid, dtitle, did in doc_rows:
        key = (etype, eid)
        if key not in entity_docs_map:
            entity_docs_map[key] = []
        entity_docs_map[key].append({"id": did, "title": dtitle})

    cu_storage_pools: dict[int, list[str]] = {}
    svc_storage_rows = db.execute(
        select(Service.compute_id, Storage.name)
        .join(ServiceStorage, ServiceStorage.service_id == Service.id)
        .join(Storage, Storage.id == ServiceStorage.storage_id)
        .where(Service.compute_id.isnot(None))
    ).all()
    for cu_id, st_name in svc_storage_rows:
        if cu_id not in cu_storage_pools:
            cu_storage_pools[cu_id] = []
        if st_name not in cu_storage_pools[cu_id]:
            cu_storage_pools[cu_id].append(st_name)

    cu_networks: dict[int, list[int]] = {}
    hw_networks: dict[int, list[int]] = {}
    if "networks" in include_set and "services" in include_set:
        for cn in db.execute(select(ComputeNetwork)).scalars().all():
            cu_networks.setdefault(cn.compute_id, []).append(cn.network_id)
        for hn in db.execute(select(HardwareNetwork)).scalars().all():
            hw_networks.setdefault(hn.hardware_id, []).append(hn.network_id)
        for net in (
            db.execute(select(Network).where(Network.gateway_hardware_id.isnot(None)))
            .scalars()
            .all()
        ):
            hw_networks.setdefault(net.gateway_hardware_id, []).append(net.id)  # type: ignore[arg-type]

    return TopologyContext(
        db=db,
        include_set=include_set,
        conflict_map=conflict_map,
        entity_tags_map=entity_tags_map,
        entity_docs_map=entity_docs_map,
        cu_storage_pools=cu_storage_pools,
        cu_networks=cu_networks,
        hw_networks=hw_networks,
        environment=environment,
        environment_id=environment_id,
        rack_id=rack_id,
    )


def build_topology_graph(
    db: Session,
    environment: str | None = None,
    environment_id: int | None = None,
    rack_id: int | None = None,
    include: str = "hardware,compute,services,storage,networks,misc,external",
) -> dict:
    """Pure callable graph builder — shared by /graph/topology and /topologies/{id}."""
    ctx = _build_topology_context(db, environment, environment_id, rack_id, include)

    nodes: list[dict] = []
    edges: list[dict] = []

    net_nodes, net_edges = _process_networks(ctx)
    nodes.extend(net_nodes)
    edges.extend(net_edges)

    if "hardware" in ctx["include_set"]:
        cluster_nodes, included_cluster_ids = _process_clusters_and_racks(ctx)
        nodes.extend(cluster_nodes)

        hw_nodes, hw_edges = _process_hardware(ctx, included_cluster_ids)
        nodes.extend(hw_nodes)
        edges.extend(hw_edges)

    cu_nodes, cu_edges = _process_compute(ctx)
    nodes.extend(cu_nodes)
    edges.extend(cu_edges)

    svc_nodes, svc_edges = _process_services(ctx)
    nodes.extend(svc_nodes)
    edges.extend(svc_edges)

    st_nodes, st_edges = _process_storage(ctx)
    nodes.extend(st_nodes)
    edges.extend(st_edges)

    nodes.extend(_process_misc(ctx))

    ext_nodes, ext_edges = _process_external(ctx)
    nodes.extend(ext_nodes)
    edges.extend(ext_edges)

    docker_nodes, docker_edges = _process_docker(ctx)
    nodes.extend(docker_nodes)
    edges.extend(docker_edges)

    return {"nodes": nodes, "edges": edges}


def _topology_etag(
    db: Session,
    environment: str | None,
    environment_id: int | None,
    rack_id: int | None,
    include: str,
) -> str:
    """Lightweight version string for topology (for ETag / If-None-Match)."""
    parts = [f"env={environment}", f"eid={environment_id}", f"rack={rack_id}", f"inc={include}"]
    for model in (Hardware, ComputeUnit, Service, Network, Storage):
        try:
            row = db.execute(select(func.max(model.updated_at))).scalar_one_or_none()
            parts.append(f"{model.__tablename__}={row!s}")
        except Exception:
            parts.append(f"{model.__tablename__}=none")
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
    return h


@router.get("/topology")
def get_topology(
    request: Request,
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    rack_id: int | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks,misc,external"),
    db: Session = Depends(get_db),
):
    etag = _topology_etag(db, environment, environment_id, rack_id, include)
    if_none_match = (request.headers.get("if-none-match") or "").strip().strip('"')
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)
    data = build_topology_graph(
        db=db,
        environment=environment,
        environment_id=environment_id,
        rack_id=rack_id,
        include=include,
    )
    return JSONResponse(content=data, headers={"ETag": f'"{etag}"'})


@router.get("/layout")
def get_layout(name: str = "default", db: Session = Depends(get_db)):
    layout = db.execute(select(GraphLayout).where(GraphLayout.name == name)).scalar_one_or_none()
    if not layout:
        return {"layout_data": None}
    return {"layout_data": layout.layout_data, "updated_at": layout.updated_at}


@router.post("/layout")
async def save_layout(
    data: LayoutUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    try:
        layout = db.execute(
            select(GraphLayout).where(GraphLayout.name == data.name)
        ).scalar_one_or_none()
        if layout:
            layout.layout_data = json.loads(data.layout_data)
        else:
            layout = GraphLayout(name=data.name, layout_data=data.layout_data)
            db.add(layout)
        db.commit()
    except Exception as e:
        db.rollback()
        _logger.exception("Failed to save graph layout: %s", e)
        raise HTTPException(
            status_code=500, detail="An internal error occurred while saving the layout."
        ) from e

    # NATS is best-effort — never fail the save response
    try:
        from app.core.nats_client import nats_client
        from app.core.subjects import TOPOLOGY_NODE_MOVED

        await nats_client.publish(
            TOPOLOGY_NODE_MOVED,
            {"layout_name": data.name, "layout_data": data.layout_data},
        )
    except Exception:
        _logger.warning("NATS publish failed for layout save (non-fatal)")

    return {"status": "ok"}


@router.post("/place-node")
def place_node(
    data: PlaceNodeInput,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    from app.services.graph_service import place_node_safe

    safe_pos = place_node_safe(db, data.node_id, environment=data.environment)
    return {"x": safe_pos.get("x"), "y": safe_pos.get("y"), "layout": "auto"}


@router.get("/layouts")
def get_layouts():
    """Return the registry of all available layout engines and presets."""
    from app.services.graph_layout import get_layouts as _get_layouts

    return _get_layouts()
