import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

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

router = APIRouter(tags=["graph"])

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
    data = {"relation": relation}
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
    # Let's do a simple bulk fetch approach if performance matters, but for now simple attribute access
    # (relying on SQLAlchemy lazy/eager loading) is fine.
    # But wait, our models don't have `tags` relationship explicitly defined in `models.py` snippet I saw?
    # Checking models.py... EntityTag exists.
    # Let's add a helper to get tags or simple ignore them for now if relation isn't easy.
    # Actually, `EntityTag` is there. Let's pre-fetch all entity tags to avoid N+1.

    entity_tags_map = {}
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

    def get_tags(etype, eid):
        return entity_tags_map.get((etype, eid), [])

    entity_docs_map = {}
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

    def get_docs(etype, eid):
        return entity_docs_map.get((etype, eid), [])

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
            hw_networks.setdefault(net.gateway_hardware_id, []).append(net.id)

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
                    id=f"e-np-{peer.network_a_id}-{peer.network_b_id}",
                    source=f"net-{peer.network_a_id}",
                    target=f"net-{peer.network_b_id}",
                    relation="peers_with",
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
        hw_query = select(Hardware)
        if rack_id is not None:
            hw_query = hw_query.where(Hardware.rack_id == rack_id)
        for hw in db.execute(hw_query).scalars():
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
            telemetry_data = None
            if hw.telemetry_data:
                try:
                    telemetry_data = json.loads(hw.telemetry_data)
                except (json.JSONDecodeError, TypeError):
                    pass
            nodes.append(
                {
                    "id": f"hw-{hw.id}",
                    "type": "hardware",
                    "ref_id": hw.id,
                    "label": hw.name,
                    "vendor": hw.vendor,
                    "role": hw.role,
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
                    "u_height": hw.u_height,
                    "rack_unit": hw.rack_unit,
                    "rack_id": hw.rack_id,
                    "rack_name": hw.rack.name if hw.rack else None,
                    "download_speed_mbps": hw.download_speed_mbps,
                    "upload_speed_mbps": hw.upload_speed_mbps,
                    "ip_conflict": conflict_map.get(("hardware", hw.id), False),
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

        # Cluster → Hardware member edges
        hw_node_ids = {f"hw-{hw.id}" for hw in db.execute(select(Hardware)).scalars()}
        for member in db.execute(select(HardwareClusterMember)).scalars().all():
            cluster_node_id = f"cluster-{member.cluster_id}"
            hw_node_id = f"hw-{member.hardware_id}"
            if member.cluster_id in included_cluster_ids and hw_node_id in hw_node_ids:
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
        q = select(Service)
        if environment_id is not None:
            q = q.where(Service.environment_id == environment_id)
        elif environment:
            q = q.where(Service.environment == environment)
        services = db.execute(q).scalars().all()
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
            links = db.execute(select(ServiceMisc)).scalars().all()
            for link in links:
                if link.service_id in service_ids:
                    edges.append(
                        build_edge_dict(
                            id=f"e-sm-{link.id}",
                            source=f"svc-{link.service_id}",
                            target=f"misc-{link.misc_id}",
                            relation="integrates_with",
                            connection_type=getattr(link, "connection_type", None),
                            bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                        )
                    )

    # 6. Storage
    if "storage" in include_set:
        for st in db.execute(select(Storage)).scalars():
            nodes.append(
                {
                    "id": f"st-{st.id}",
                    "type": "storage",
                    "ref_id": st.id,
                    "label": st.name,
                    "kind": st.kind,
                    "capacity_gb": st.capacity_gb,
                    "used_gb": st.used_gb,
                    "vendor": st.hardware.vendor if st.hardware else None,
                    "icon_slug": st.hardware.vendor_icon_slug if st.hardware else None,
                    "tags": get_tags("storage", st.id),
                }
            )
            # Edge: Storage → Hardware (attached_to)
            if st.hardware_id and "hardware" in include_set:
                edges.append(
                    build_edge_dict(
                        id=f"e-hw-st-{st.id}",
                        source=f"hw-{st.hardware_id}",
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
            for link in db.execute(select(ExternalNodeNetwork)).scalars().all():
                edges.append(
                    build_edge_dict(
                        id=f"e-ext-net-{link.id}",
                        source=f"ext-{link.external_node_id}",
                        target=f"net-{link.network_id}",
                        relation="connects_to",
                        connection_type=getattr(link, "connection_type", None),
                        bandwidth_mbps=getattr(link, "bandwidth_mbps", None),
                    )
                )

        # Service → External edges
        if "services" in include_set:
            for link in db.execute(select(ServiceExternalNode)).scalars().all():
                edges.append(
                    build_edge_dict(
                        id=f"e-svc-ext-{link.id}",
                        source=f"svc-{link.service_id}",
                        target=f"ext-{link.external_node_id}",
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


@router.get("/topology")
def get_topology(
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    rack_id: int | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks,misc,external"),
    db: Session = Depends(get_db),
):
    return build_topology_graph(
        db=db,
        environment=environment,
        environment_id=environment_id,
        rack_id=rack_id,
        include=include,
    )


@router.get("/layout")
def get_layout(name: str = "default", db: Session = Depends(get_db)):
    layout = db.execute(select(GraphLayout).where(GraphLayout.name == name)).scalar_one_or_none()
    if not layout:
        return {"layout_data": None}
    return {"layout_data": layout.layout_data, "updated_at": layout.updated_at}


@router.post("/layout")
def save_layout(data: LayoutUpdate, db: Session = Depends(get_db)):
    try:
        layout = db.execute(
            select(GraphLayout).where(GraphLayout.name == data.name)
        ).scalar_one_or_none()
        if layout:
            layout.layout_data = data.layout_data
        else:
            layout = GraphLayout(name=data.name, layout_data=data.layout_data)
            db.add(layout)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        _logger.exception("Failed to save graph layout: %s", e)
        raise HTTPException(
            status_code=500, detail="An internal error occurred while saving the layout."
        ) from e


@router.post("/place-node")
def place_node(data: PlaceNodeInput, db: Session = Depends(get_db)):
    from app.services.graph_service import place_node_safe

    safe_pos = place_node_safe(db, data.node_id, environment=data.environment)
    return {"x": safe_pos.get("x"), "y": safe_pos.get("y"), "layout": "auto"}


@router.get("/layouts")
def get_layouts():
    """Return the registry of all available layout engines and presets."""
    from app.services.graph_layout import get_layouts as _get_layouts

    return _get_layouts()
