import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Integer, Select, String, cast, func, literal, null, select, union_all
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.audit import log_audit
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
    MapPinnedEntity,
    MiscItem,
    Network,
    NetworkPeer,
    Rack,
    ScanResult,
    Service,
    ServiceDependency,
    ServiceExternalNode,
    ServiceMisc,
    ServiceStorage,
    Storage,
    Tag,
    TopologyNode,
)
from app.db.session import get_db
from app.services.ip_reservation import bulk_conflict_map

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["graph"], dependencies=[require_scope("read", "*")])


def _edge_arm(
    tag: str,
    model: type[Any],
    src_col: str,
    tgt_col: str,
    *,
    has_conn: bool = True,
    has_bw: bool = True,
) -> Select[Any]:
    """Build one SELECT arm of the edge UNION ALL CTE."""
    t = model.__table__
    return select(
        literal(tag).label("edge_type"),
        t.c[src_col].label("src_id"),
        t.c[tgt_col].label("tgt_id"),
        (
            t.c.connection_type.label("connection_type")
            if has_conn
            else cast(null(), String).label("connection_type")
        ),
        (
            t.c.bandwidth_mbps.label("bandwidth_mbps")
            if has_bw
            else cast(null(), Integer).label("bandwidth_mbps")
        ),
        t.c.id.label("row_id"),
    )


def _preload_edge_maps(db: Session) -> dict:
    """CTE-based bulk preload of all edge/relation data in a single round-trip.

    Returns a dict of pre-built lookup maps that build_topology_graph uses
    to emit edges without issuing separate queries for each join table.

    Uses SQLAlchemy expression API (union_all + select) instead of raw SQL
    for defense-in-depth parameterization.
    """
    cte = union_all(
        _edge_arm("hn", HardwareNetwork, "hardware_id", "network_id"),
        _edge_arm("cn", ComputeNetwork, "compute_id", "network_id"),
        _edge_arm("hh", HardwareConnection, "source_hardware_id", "target_hardware_id"),
        _edge_arm("np", NetworkPeer, "network_a_id", "network_b_id"),
        _edge_arm("dep", ServiceDependency, "service_id", "depends_on_id"),
        _edge_arm("ss", ServiceStorage, "service_id", "storage_id"),
        _edge_arm("sm", ServiceMisc, "service_id", "misc_id"),
        _edge_arm("extnet", ExternalNodeNetwork, "external_node_id", "network_id"),
        _edge_arm("svcext", ServiceExternalNode, "service_id", "external_node_id"),
        _edge_arm(
            "hcm", HardwareClusterMember, "cluster_id", "hardware_id", has_conn=False, has_bw=False
        ),
    ).cte("all_edges")

    stmt = select(
        cte.c.edge_type,
        cte.c.src_id,
        cte.c.tgt_id,
        cte.c.connection_type,
        cte.c.bandwidth_mbps,
        cte.c.row_id,
    )

    result: dict[str, list] = {}
    try:
        rows = db.execute(stmt).all()
        for edge_type, src_id, tgt_id, conn_type, bw, row_id in rows:
            result.setdefault(edge_type, []).append((src_id, tgt_id, conn_type, bw, row_id))
    except Exception:
        _logger.debug("CTE edge preload failed; falling back to per-table queries")
    return result


_ALLOWED_CONNECTION_TYPES = {
    "ethernet",
    "wireless",
    "tunnel",
    "wg",
    "vpn",
    "ssh",
    "fiber",
    "bgp",
    "vlan",
    "management",
    "backup",
    "heartbeat",
}
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
    ("e-np-", NetworkPeer),
]


def _parse_deletable_edge(edge_id: str) -> tuple[Any, Any]:
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
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
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
    log_audit(
        db,
        request,
        user_id=user_id,
        action="edge_deleted",
        resource=f"edge:{edge_id}",
        status="ok",
        severity="warn",
    )


@router.patch("/edges/{edge_id}", status_code=200)
def update_edge_type(
    edge_id: str,
    payload: EdgeUpdatePayload,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> dict[str, Any]:
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
        if hasattr(row, "source"):
            row.source = "manual"
        db.commit()
    log_audit(
        db,
        request,
        user_id=user_id,
        action="edge_updated",
        resource=f"edge:{edge_id}",
        status="ok",
    )
    return {"status": "ok", "connection_type": normalized}


class LayoutUpdate(BaseModel):
    name: str = "default"
    layout_data: str  # JSON string
    constraints: dict = Field(default_factory=dict)
    map_id: int | None = None


class PlaceNodeInput(BaseModel):
    node_id: str
    environment: str = "default"


def build_topology_graph(
    db: Session,
    environment: str | None = None,
    environment_id: int | None = None,
    rack_id: int | None = None,
    include: str = "hardware,compute,services,storage,networks,misc,external",
) -> dict:
    """Pure callable graph builder — shared by /graph/topology and /topologies/{id}."""
    include_set = {i.strip().lower() for i in include.split(",")}
    nodes: list[dict] = []
    edges: list[dict] = []

    # Bulk-compute IP conflict flags once per request to avoid N individual queries
    conflict_map = bulk_conflict_map(db)  # (etype, eid) -> bool

    # Helper to fetch tags for a set of entities
    # Optimization: Loading tags for all entities can be N+1 if not careful.
    # For v1 homelab scale, we can just fetch them or rely on lazy loading if eager is set.
    # Let's do a simple bulk fetch approach if performance matters, but for now simple
    # attribute access (relying on SQLAlchemy lazy/eager loading) is fine.
    # But wait, our models don't have `tags` relationship explicitly defined in
    # `models.py` snippet I saw?
    # Checking models.py... EntityTag exists.
    # Let's add a helper to get tags or simple ignore them for now if relation isn't easy.
    # Actually, `EntityTag` is there. Let's pre-fetch all entity tags to avoid N+1.

    entity_tags_map: dict[Any, Any] = {}
    # Bulk-fetch all (entity_type, entity_id, tag_name) rows in a single query
    # to avoid N+1 per entity.
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

    def get_tags(etype: Any, eid: Any) -> list[Any]:
        result: list[Any] = entity_tags_map.get((etype, eid), [])
        return result

    entity_docs_map: dict[Any, Any] = {}
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

    def get_docs(etype: Any, eid: Any) -> list[Any]:
        result: list[Any] = entity_docs_map.get((etype, eid), [])
        return result

    # Pre-build compute_id → [storage_pool_names] via service→storage relationships
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

    # Pre-build lookup maps for service→network implicit edges
    # (compute_id → [network_id, ...]) and (hardware_id → [network_id, ...])
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

    # 1. Networks — emitted first so layout engines (Dagre/ELK) rank them as roots
    if "networks" in include_set:
        for net in db.execute(select(Network)).scalars():
            nodes.append(
                {
                    "id": f"net-{net.id}",
                    "type": "network",
                    "ref_id": net.id,
                    "label": net.name,
                    "cidr": net.cidr,
                    "icon_slug": net.icon_slug,
                    "tags": get_tags("networks", net.id),
                }
            )

        # Compute → Network membership edges
        if "compute" in include_set:
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

        # Hardware → Network gateway edges
        if "hardware" in include_set:
            for net in db.execute(
                select(Network).where(Network.gateway_hardware_id.isnot(None))
            ).scalars():
                edges.append(
                    build_edge_dict(
                        id=f"e-gw-{net.id}",
                        source=f"hw-{net.gateway_hardware_id}",
                        target=f"net-{net.id}",
                        relation="routes",
                        connection_type="ethernet",
                    )
                )

        # Hardware → Network membership edges
        if "hardware" in include_set:
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

        # Network ↔ Network peer edges
        all_peers = db.execute(select(NetworkPeer)).scalars().all()
        for peer in all_peers:
            edges.append(
                build_edge_dict(
                    id=f"e-np-{peer.id}",
                    source=f"net-{peer.network_a_id}",
                    target=f"net-{peer.network_b_id}",
                    relation="peers_with",
                    connection_type=getattr(peer, "connection_type", None),
                    bandwidth_mbps=getattr(peer, "bandwidth_mbps", None),
                )
            )

    # 2. Clusters (emitted before hardware so layout engines rank them as roots)
    if "hardware" in include_set:
        clusters = db.execute(select(HardwareCluster)).scalars().all()
        included_cluster_ids: set[int] = set()
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
                    "docs": get_docs("hardware_cluster", cluster.id),
                }
            )

    # 2b. Racks (group nodes)
    if "hardware" in include_set:
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

    # 3. Hardware
    if "hardware" in include_set:
        hw_query = select(Hardware).options(
            selectinload(Hardware.storage_items),
            joinedload(Hardware.rack),
        )
        if rack_id is not None:
            hw_query = hw_query.where(Hardware.rack_id == rack_id)

        # Execute once; reuse list for monitor batch-load and node iteration.
        _all_hw = db.execute(hw_query).unique().scalars().all()
        _all_hw_ids = [hw.id for hw in _all_hw]
        _monitors = (
            (db.query(HardwareMonitor).filter(HardwareMonitor.hardware_id.in_(_all_hw_ids)).all())
            if _all_hw_ids
            else []
        )
        _monitor_map = {m.hardware_id: m for m in _monitors}

        for hw in _all_hw:
            # Build storage_summary by aggregating attached storage items
            storage_summary = None
            if hw.storage_items:
                total_gb = sum(s.capacity_gb or 0 for s in hw.storage_items)
                used_gb = sum(s.used_gb or 0 for s in hw.storage_items)
                kinds = list(
                    dict.fromkeys(s.kind for s in hw.storage_items if s.kind)
                )  # preserves order, deduped
                primary_pool = hw.storage_items[0].name if hw.storage_items else None
                storage_summary = {
                    "total_gb": total_gb,
                    "used_gb": used_gb
                    if any(s.used_gb is not None for s in hw.storage_items)
                    else None,
                    "types": kinds,
                    "primary_pool": primary_pool,
                    "count": len(hw.storage_items),
                }
            telemetry_data = hw.telemetry_data if isinstance(hw.telemetry_data, dict) else None
            nodes.append(
                {
                    "id": f"hw-{hw.id}",
                    "type": "hardware",
                    "ref_id": hw.id,
                    "label": hw.name,
                    "vendor": hw.vendor,
                    # COALESCE(h.role, n.type): guarantee role is always populated so the
                    # frontend shape selector always has a value to match against.
                    "role": hw.role or "hardware",
                    "icon_slug": hw.custom_icon or hw.vendor_icon_slug,
                    "ip_address": hw.ip_address,
                    "storage_summary": storage_summary,
                    "tags": get_tags("hardware", hw.id),
                    "docs": get_docs("hardware", hw.id),
                    "status": hw.status or "unknown",
                    "status_override": hw.status_override or None,
                    "telemetry_status": hw.telemetry_status or "unknown",
                    "telemetry_data": telemetry_data,
                    "telemetry_last_polled": hw.telemetry_last_polled.isoformat()
                    if hw.telemetry_last_polled
                    else None,
                    "device_type": (
                        db.query(ScanResult.device_type)
                        .filter(ScanResult.id == hw.source_scan_result_id)
                        .scalar()
                    )
                    if hw.source_scan_result_id
                    else None,
                    "u_height": hw.u_height,
                    "rack_unit": hw.rack_unit,
                    "rack_id": hw.rack_id,
                    "rack_name": hw.rack.name if hw.rack else None,
                    "download_speed_mbps": hw.download_speed_mbps,
                    "upload_speed_mbps": hw.upload_speed_mbps,
                    "ip_conflict": conflict_map.get(("hardware", hw.id), False),
                    "monitor_status": _monitor_map[hw.id].last_status
                    if hw.id in _monitor_map
                    else None,
                    "monitor_latency_ms": _monitor_map[hw.id].latency_ms
                    if hw.id in _monitor_map
                    else None,
                    "monitor_last_checked_at": _monitor_map[hw.id].last_checked_at
                    if hw.id in _monitor_map
                    else None,
                    "monitor_uptime_pct_24h": _monitor_map[hw.id].uptime_pct_24h
                    if hw.id in _monitor_map
                    else None,
                    "proxmox_node_name": hw.proxmox_node_name,
                    "integration_config_id": hw.integration_config_id,
                }
            )
            # Rack → Hardware member edges
            if hw.rack_id:
                edges.append(
                    build_edge_dict(
                        id=f"e-rack-{hw.rack_id}-hw-{hw.id}",
                        source=f"rack-{hw.rack_id}",
                        target=f"hw-{hw.id}",
                        relation="rack_member",
                    )
                )

        # Cluster → Hardware/Service member edges
        # Build hw set from already-loaded data; fetch only Service PKs (no full rows).
        hw_node_ids = {f"hw-{hw.id}" for hw in _all_hw}
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

        # Hardware → Hardware direct connection edges
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

    # 5. Compute
    if "compute" in include_set:
        q = select(ComputeUnit)
        if environment_id is not None:
            q = q.where(ComputeUnit.environment_id == environment_id)
        elif environment:
            q = q.where(ComputeUnit.environment == environment)
        for cu in db.execute(q).scalars():
            pools = cu_storage_pools.get(cu.id, [])
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
                    "tags": get_tags("compute", cu.id),
                    "docs": get_docs("compute_unit", cu.id),
                    "ip_conflict": conflict_map.get(("compute_unit", cu.id), False),
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
            # Link to Hardware
            if "hardware" in include_set:
                edges.append(
                    build_edge_dict(
                        id=f"e-hw-cu-{cu.id}",
                        source=f"hw-{cu.hardware_id}",
                        target=f"cu-{cu.id}",
                        relation="hosts",
                    )
                )

    # 6. Services
    if "services" in include_set:
        q = select(Service).options(  # type: ignore[assignment]
            joinedload(Service.compute_unit),
            joinedload(Service.hardware),
        )
        if environment_id is not None:
            q = q.where(Service.environment_id == environment_id)
        elif environment:
            q = q.where(Service.environment == environment)
        services: list[Any] = db.execute(q).unique().scalars().all()  # type: ignore[assignment]
        service_ids = {s.id for s in services}

        for svc in services:
            effective_ip = (
                svc.ip_address
                or (svc.compute_unit.ip_address if svc.compute_unit else None)
                or (svc.hardware.ip_address if svc.hardware else None)
            )
            parsed_ports = []
            if svc.ports_json:
                try:
                    maybe_ports = json.loads(svc.ports_json)
                    if isinstance(maybe_ports, list):
                        parsed_ports = maybe_ports
                except Exception:
                    parsed_ports = []
            nodes.append(
                {
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
                    "tags": get_tags("services", svc.id),
                    "docs": get_docs("service", svc.id),
                    "ip_conflict": bool(svc.ip_conflict),
                }
            )
            # Link to Compute
            if svc.compute_id and "compute" in include_set:
                edges.append(
                    build_edge_dict(
                        id=f"e-cu-svc-{svc.id}",
                        source=f"cu-{svc.compute_id}",
                        target=f"svc-{svc.id}",
                        relation="runs",
                    )
                )
            # Link to Hardware (direct)
            elif svc.hardware_id and "hardware" in include_set:
                edges.append(
                    build_edge_dict(
                        id=f"e-hw-svc-{svc.id}",
                        source=f"hw-{svc.hardware_id}",
                        target=f"svc-{svc.id}",
                        relation="hosts",
                    )
                )

            # Service → Network implicit edges
            # A service is considered on any network its host compute unit or hardware belongs to
            if "networks" in include_set:
                seen_nets: set[int] = set()
                if svc.compute_id:
                    for net_id in cu_networks.get(svc.compute_id, []):
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
                    for net_id in hw_networks.get(svc.hardware_id, []):
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

        # Service → Service dependencies
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

        # Service → Storage
        if "storage" in include_set:
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

        # Service → Misc
        if "misc" in include_set:
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

    # 6. Storage
    if "storage" in include_set:
        proxmox_hw_lookup: dict[tuple[int, str], Hardware] = {}
        for hw in db.execute(select(Hardware)).scalars():
            if hw.integration_config_id and hw.proxmox_node_name:
                proxmox_hw_lookup[(hw.integration_config_id, hw.proxmox_node_name.strip())] = hw

        for st in (
            db.execute(select(Storage).options(joinedload(Storage.hardware))).unique().scalars()
        ):
            inferred_hw_id = st.hardware_id
            inferred_vendor = st.hardware.vendor if st.hardware else None
            inferred_icon = st.hardware.vendor_icon_slug if st.hardware else None

            # Queue-mode Proxmox storage can arrive before node rows are accepted.
            # Infer node association from "<pool>@<node>" naming so the map links it.
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
                    "tags": get_tags("storage", st.id),
                    "hardware_id": inferred_hw_id,
                    "integration_config_id": st.integration_config_id,
                }
            )
            # Edge: Storage → Hardware (attached_to)
            if inferred_hw_id and "hardware" in include_set:
                edges.append(
                    build_edge_dict(
                        id=f"e-hw-st-{st.id}",
                        source=f"hw-{inferred_hw_id}",
                        target=f"st-{st.id}",
                        relation="has_storage",
                    )
                )

    # 7. Misc
    if "misc" in include_set:
        for m in db.execute(select(MiscItem)).scalars():
            nodes.append(
                {
                    "id": f"misc-{m.id}",
                    "type": "misc",
                    "ref_id": m.id,
                    "label": m.name,
                    "tags": get_tags("misc", m.id),
                }
            )

    # 8. External Nodes (off-prem / cloud)
    if "external" in include_set:
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
                    "tags": get_tags("external", ext.id),
                    "meta": {
                        "provider": ext.provider,
                        "kind": ext.kind,
                        "region": ext.region,
                        "ip_address": ext.ip_address,
                    },
                }
            )

        # External → Network edges
        if "networks" in include_set:
            for link in db.execute(select(ExternalNodeNetwork)).scalars().all():  # type: ignore[assignment]
                _conn_type = getattr(link, "connection_type", None)
                if not _conn_type or _conn_type == "ethernet":
                    _raw_lt = getattr(link, "link_type", None)
                    if _raw_lt:
                        _conn_type = _raw_lt
                edges.append(
                    build_edge_dict(
                        id=f"e-ext-net-{link.id}",
                        source=f"ext-{link.external_node_id}",  # type: ignore[attr-defined]
                        target=f"net-{link.network_id}",  # type: ignore[attr-defined]
                        relation="connects_to",
                        connection_type=_conn_type,
                        bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                    )
                )

        # Service → External edges
        if "services" in include_set:
            for link in db.execute(select(ServiceExternalNode)).scalars().all():  # type: ignore[assignment]
                edges.append(
                    build_edge_dict(
                        id=f"e-svc-ext-{link.id}",
                        source=f"svc-{link.service_id}",
                        target=f"ext-{link.external_node_id}",  # type: ignore[attr-defined]
                        relation="depends_on",
                        connection_type=getattr(link, "connection_type", None),
                        bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                    )
                )

    # ── Docker networks + containers ──────────────────────────────────────────
    if "docker" in include_set:
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
                    "tags": get_tags("networks", dnet.id),
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
                    "tags": get_tags("services", dsvc.id),
                }
            )

            # Container → its host network edge (via ip or compute/hardware networks)
            if dsvc.compute_id and dsvc.compute_id in cu_networks:
                for net_id in cu_networks[dsvc.compute_id]:
                    if net_id in docker_net_ids:
                        edges.append(
                            build_edge_dict(
                                id=f"e-docker-cn-{dsvc.id}-{net_id}",
                                source=f"svc-{dsvc.id}",
                                target=f"net-{net_id}",
                                relation="on_network",
                            )
                        )
            elif dsvc.hardware_id and dsvc.hardware_id in hw_networks:
                for net_id in hw_networks[dsvc.hardware_id]:
                    if net_id in docker_net_ids:
                        edges.append(
                            build_edge_dict(
                                id=f"e-docker-hn-{dsvc.id}-{net_id}",
                                source=f"svc-{dsvc.id}",
                                target=f"net-{net_id}",
                                relation="on_network",
                            )
                        )

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
    # Connection join tables have no updated_at — use row counts so any add/remove busts the ETag
    for join_model in (HardwareNetwork, ComputeNetwork, NetworkPeer, HardwareConnection):
        try:
            cnt = db.execute(select(func.count()).select_from(join_model)).scalar_one()
            parts.append(f"{join_model.__tablename__}_cnt={cnt}")
        except Exception:
            parts.append(f"{join_model.__tablename__}_cnt=none")
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
    return h


@router.get("/topology")
def get_topology(
    request: Request,
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    rack_id: int | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks,misc,external"),
    map_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
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
    # Filter nodes/edges by map membership when map_id is specified
    if map_id is not None:
        member_rows = db.execute(
            select(TopologyNode.entity_type, TopologyNode.entity_id).where(
                TopologyNode.topology_id == map_id
            )
        ).all()
        pinned_rows = db.execute(
            select(MapPinnedEntity.entity_type, MapPinnedEntity.entity_id)
        ).all()
        # Build allowed node ID set using the same prefix format as build_topology_graph
        _TYPE_PREFIX = {
            "hardware": "hw",
            "network": "net",
            "cluster": "cluster",
            "compute": "cu",
            "service": "svc",
            "storage": "st",
            "misc": "misc",
            "external": "ext",
        }
        allowed_ids = set()
        for entity_type, entity_id in list(member_rows) + list(pinned_rows):
            prefix = _TYPE_PREFIX.get(entity_type, entity_type)
            allowed_ids.add(f"{prefix}-{entity_id}")
        nodes = [n for n in data.get("nodes", []) if n.get("id") in allowed_ids]
        node_id_set = {n["id"] for n in nodes}
        edges = [
            e
            for e in data.get("edges", [])
            if e.get("source") in node_id_set and e.get("target") in node_id_set
        ]
        data = {**data, "nodes": nodes, "edges": edges}
    return JSONResponse(content=data, headers={"ETag": f'"{etag}"', "Cache-Control": "no-cache"})


@router.get("/layout")
def get_layout(
    name: str = "default",
    map_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if map_id is not None:
        layout = db.execute(
            select(GraphLayout).where(GraphLayout.topology_id == map_id)
        ).scalar_one_or_none()
    else:
        layout = db.execute(
            select(GraphLayout).where(GraphLayout.name == name)
        ).scalar_one_or_none()
    if not layout:
        return {"layout_data": None}
    return {"layout_data": layout.layout_data, "updated_at": layout.updated_at}


@router.post("/layout")
async def save_layout(
    data: LayoutUpdate,
    db: Session = Depends(get_db),
    _: Any = Depends(require_write_auth),
) -> dict[str, Any]:
    try:
        try:
            parsed_layout = json.loads(data.layout_data)
        except (json.JSONDecodeError, TypeError) as err:
            raise HTTPException(
                status_code=422,
                detail="layout_data must be valid JSON",
            ) from err
        if not isinstance(parsed_layout, dict):
            raise HTTPException(
                status_code=422,
                detail="layout_data must be a JSON object",
            )
        if data.map_id is not None:
            layout = db.execute(
                select(GraphLayout).where(GraphLayout.topology_id == data.map_id)
            ).scalar_one_or_none()
        else:
            layout = db.execute(
                select(GraphLayout).where(GraphLayout.name == data.name)
            ).scalar_one_or_none()
        if layout:
            layout.layout_data = parsed_layout
        else:
            layout = GraphLayout(
                name=f"map-{data.map_id}" if data.map_id else data.name,
                layout_data=parsed_layout,
                topology_id=data.map_id,
            )
            db.add(layout)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
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
    _: Any = Depends(require_write_auth),
) -> dict[str, Any]:
    from app.services.graph_service import place_node_safe

    safe_pos = place_node_safe(db, data.node_id, environment=data.environment)
    return {"x": safe_pos.get("x"), "y": safe_pos.get("y"), "layout": "auto"}


@router.get("/layouts")
def get_layouts() -> Any:
    """Return the registry of all available layout engines and presets."""
    from app.services.graph_layout import get_layouts as _get_layouts

    return _get_layouts()
