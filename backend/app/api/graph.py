import json
import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.services.ip_reservation import bulk_conflict_map
from app.db.models import (
    Hardware,
    HardwareCluster,
    HardwareClusterMember,
    ComputeUnit,
    Service,
    ServiceDependency,
    Storage,
    ServiceStorage,
    Network,
    ComputeNetwork,
    HardwareNetwork,
    MiscItem,
    ServiceMisc,
    ExternalNode,
    ExternalNodeNetwork,
    ServiceExternalNode,
    GraphLayout,
    Tag,
    EntityTag,
)

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["graph"])


class LayoutUpdate(BaseModel):
    name: str = "default"
    layout_data: str  # JSON string


@router.get("/topology")
def get_topology(
    environment: str | None = Query(None),
    environment_id: int | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks,misc,external"),
    db: Session = Depends(get_db),
):
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
    link_rows = db.execute(select(EntityTag.entity_type, EntityTag.entity_id, Tag.name)
                           .join(Tag, EntityTag.tag_id == Tag.id)).all()
    
    for etype, eid, tname in link_rows:
        key = (etype, eid)
        if key not in entity_tags_map:
            entity_tags_map[key] = []
        entity_tags_map[key].append(tname)

    def get_tags(etype, eid):
        return entity_tags_map.get((etype, eid), [])

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
        for net in db.execute(select(Network).where(Network.gateway_hardware_id.isnot(None))).scalars().all():
            hw_networks.setdefault(net.gateway_hardware_id, []).append(net.id)

    # 1. Networks — emitted first so layout engines (Dagre/ELK) rank them as roots
    if "networks" in include_set:
        for net in db.execute(select(Network)).scalars():
            nodes.append({
                "id": f"net-{net.id}",
                "type": "network",
                "ref_id": net.id,
                "label": net.name,
                "cidr": net.cidr,
                "icon_slug": net.icon_slug,
                "tags": get_tags("networks", net.id)
            })

        # Compute → Network membership edges
        if "compute" in include_set:
            cns = db.execute(select(ComputeNetwork)).scalars().all()
            for cn in cns:
                edges.append({
                    "id": f"e-cn-{cn.id}",
                    "source": f"cu-{cn.compute_id}",
                    "target": f"net-{cn.network_id}",
                    "relation": "connects_to",
                })

        # Hardware → Network gateway edges
        if "hardware" in include_set:
            for net in db.execute(select(Network).where(Network.gateway_hardware_id.isnot(None))).scalars():
                edges.append({
                    "id": f"e-gw-{net.id}",
                    "source": f"hw-{net.gateway_hardware_id}",
                    "target": f"net-{net.id}",
                    "relation": "routes",
                })

        # Hardware → Network membership edges
        if "hardware" in include_set:
            hns = db.execute(select(HardwareNetwork)).scalars().all()
            for hn in hns:
                edges.append({
                    "id": f"e-hn-{hn.id}",
                    "source": f"hw-{hn.hardware_id}",
                    "target": f"net-{hn.network_id}",
                    "relation": "on_network",
                })

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
            nodes.append({
                "id": f"cluster-{cluster.id}",
                "type": "cluster",
                "ref_id": cluster.id,
                "label": cluster.name,
                "environment": cluster.environment,
                "member_count": len(cluster.members),
            })

    # 3. Hardware
    if "hardware" in include_set:
        for hw in db.execute(select(Hardware)).scalars():
            # Build storage_summary by aggregating attached storage items
            storage_summary = None
            if hw.storage_items:
                total_gb = sum(s.capacity_gb or 0 for s in hw.storage_items)
                used_gb = sum(s.used_gb or 0 for s in hw.storage_items)
                kinds = list(dict.fromkeys(s.kind for s in hw.storage_items if s.kind))  # preserves order, deduped
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
                    telemetry_data = json.loads(hw.telemetry_data)
                except (json.JSONDecodeError, TypeError):
                    pass
            nodes.append({
                "id": f"hw-{hw.id}",
                "type": "hardware",
                "ref_id": hw.id,
                "label": hw.name,
                "vendor": hw.vendor,
                "role": hw.role,
                "icon_slug": hw.vendor_icon_slug,
                "ip_address": hw.ip_address,
                "storage_summary": storage_summary,
                "tags": get_tags("hardware", hw.id),
                "telemetry_status": hw.telemetry_status or "unknown",
                "telemetry_data": telemetry_data,
                "telemetry_last_polled": hw.telemetry_last_polled.isoformat() if hw.telemetry_last_polled else None,
                "u_height": hw.u_height,
                "rack_unit": hw.rack_unit,
                "ip_conflict": conflict_map.get(("hardware", hw.id), False),
            })

        # Cluster → Hardware member edges
        hw_node_ids = {f"hw-{hw.id}" for hw in db.execute(select(Hardware)).scalars()}
        for member in db.execute(select(HardwareClusterMember)).scalars().all():
            cluster_node_id = f"cluster-{member.cluster_id}"
            hw_node_id = f"hw-{member.hardware_id}"
            if member.cluster_id in included_cluster_ids and hw_node_id in hw_node_ids:
                edges.append({
                    "id": f"e-cluster-{member.cluster_id}-hw-{member.hardware_id}",
                    "source": cluster_node_id,
                    "target": hw_node_id,
                    "relation": "cluster_member",
                })

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
            nodes.append({
                "id": f"cu-{cu.id}",
                "type": "compute",
                "ref_id": cu.id,
                "label": cu.name,
                "kind": cu.kind,
                "icon_slug": cu.icon_slug,
                "ip_address": cu.ip_address,
                "storage_allocated": storage_allocated,
                "tags": get_tags("compute", cu.id),
                "ip_conflict": conflict_map.get(("compute_unit", cu.id), False),
            })
            # Link to Hardware
            if "hardware" in include_set:
                edges.append({
                    "id": f"e-hw-cu-{cu.id}",
                    "source": f"hw-{cu.hardware_id}",
                    "target": f"cu-{cu.id}",
                    "relation": "hosts",
                })

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
            nodes.append({
                "id": f"svc-{svc.id}",
                "type": "service",
                "ref_id": svc.id,
                "label": svc.name,
                "icon_slug": svc.icon_slug,
                "ip_address": effective_ip,
                "compute_id": svc.compute_id,
                "hardware_id": svc.hardware_id,
                "tags": get_tags("services", svc.id),
                "ip_conflict": bool(svc.ip_conflict),
            })
            # Link to Compute
            if svc.compute_id and "compute" in include_set:
                edges.append({
                    "id": f"e-cu-svc-{svc.id}",
                    "source": f"cu-{svc.compute_id}",
                    "target": f"svc-{svc.id}",
                    "relation": "runs",
                })
            # Link to Hardware (direct)
            elif svc.hardware_id and "hardware" in include_set:
                edges.append({
                    "id": f"e-hw-svc-{svc.id}",
                    "source": f"hw-{svc.hardware_id}",
                    "target": f"svc-{svc.id}",
                    "relation": "hosts",
                })

            # Service → Network implicit edges
            # A service is considered on any network its host compute unit or hardware belongs to
            if "networks" in include_set:
                seen_nets: set[int] = set()
                if svc.compute_id:
                    for net_id in cu_networks.get(svc.compute_id, []):
                        if net_id not in seen_nets:
                            seen_nets.add(net_id)
                            edges.append({
                                "id": f"e-svc-net-{svc.id}-{net_id}",
                                "source": f"svc-{svc.id}",
                                "target": f"net-{net_id}",
                                "relation": "on_network",
                            })
                elif svc.hardware_id:
                    for net_id in hw_networks.get(svc.hardware_id, []):
                        if net_id not in seen_nets:
                            seen_nets.add(net_id)
                            edges.append({
                                "id": f"e-svc-net-{svc.id}-{net_id}",
                                "source": f"svc-{svc.id}",
                                "target": f"net-{net_id}",
                                "relation": "on_network",
                            })

        # Service → Service dependencies
        deps = db.execute(select(ServiceDependency)).scalars().all()
        for dep in deps:
            if dep.service_id in service_ids and dep.depends_on_id in service_ids:
                edges.append({
                    "id": f"e-dep-{dep.id}",
                    "source": f"svc-{dep.service_id}",
                    "target": f"svc-{dep.depends_on_id}",
                    "relation": "depends_on",
                })

        # Service → Storage
        if "storage" in include_set:
            links = db.execute(select(ServiceStorage)).scalars().all()
            for link in links:
                if link.service_id in service_ids:
                    edges.append({
                        "id": f"e-ss-{link.id}",
                        "source": f"svc-{link.service_id}",
                        "target": f"st-{link.storage_id}",
                        "relation": "uses",
                    })

        # Service → Misc
        if "misc" in include_set:
            links = db.execute(select(ServiceMisc)).scalars().all()
            for link in links:
                if link.service_id in service_ids:
                    edges.append({
                        "id": f"e-sm-{link.id}",
                        "source": f"svc-{link.service_id}",
                        "target": f"misc-{link.misc_id}",
                        "relation": "integrates_with",
                    })

    # 6. Storage
    if "storage" in include_set:
        for st in db.execute(select(Storage)).scalars():
            nodes.append({
                "id": f"st-{st.id}",
                "type": "storage",
                "ref_id": st.id,
                "label": st.name,
                "kind": st.kind,
                "capacity_gb": st.capacity_gb,
                "used_gb": st.used_gb,
                "vendor": st.hardware.vendor if st.hardware else None,
                "icon_slug": st.hardware.vendor_icon_slug if st.hardware else None,
                "tags": get_tags("storage", st.id)
            })
            # Edge: Storage → Hardware (attached_to)
            if st.hardware_id and "hardware" in include_set:
                edges.append({
                    "id": f"e-hw-st-{st.id}",
                    "source": f"hw-{st.hardware_id}",
                    "target": f"st-{st.id}",
                    "relation": "has_storage",
                })

    # 7. Misc
    if "misc" in include_set:
        for m in db.execute(select(MiscItem)).scalars():
            nodes.append({
                "id": f"misc-{m.id}",
                "type": "misc",
                "ref_id": m.id,
                "label": m.name,
                "tags": get_tags("misc", m.id)
            })

    # 8. External Nodes (off-prem / cloud)
    if "external" in include_set:
        for ext in db.execute(select(ExternalNode)).scalars():
            if environment and ext.environment and ext.environment != environment:
                continue
            nodes.append({
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
            })

        # External → Network edges
        if "networks" in include_set:
            for link in db.execute(select(ExternalNodeNetwork)).scalars().all():
                edges.append({
                    "id": f"e-ext-net-{link.id}",
                    "source": f"ext-{link.external_node_id}",
                    "target": f"net-{link.network_id}",
                    "relation": "connects_to",
                })

        # Service → External edges
        if "services" in include_set:
            for link in db.execute(select(ServiceExternalNode)).scalars().all():
                edges.append({
                    "id": f"e-svc-ext-{link.id}",
                    "source": f"svc-{link.service_id}",
                    "target": f"ext-{link.external_node_id}",
                    "relation": "depends_on",
                })

    return {"nodes": nodes, "edges": edges}


@router.get("/layout")
def get_layout(name: str = "default", db: Session = Depends(get_db)):
    layout = db.execute(select(GraphLayout).where(GraphLayout.name == name)).scalar_one_or_none()
    if not layout:
        return {"layout_data": None}
    return {"layout_data": layout.layout_data, "updated_at": layout.updated_at}


@router.post("/layout")
def save_layout(data: LayoutUpdate, db: Session = Depends(get_db)):
    layout = db.execute(select(GraphLayout).where(GraphLayout.name == data.name)).scalar_one_or_none()
    if layout:
        layout.layout_data = data.layout_data
    else:
        layout = GraphLayout(name=data.name, layout_data=data.layout_data)
        db.add(layout)
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        _logger.exception("Failed to save graph layout: %s", e)
        raise HTTPException(status_code=500, detail="An internal error occurred while saving the layout.")

    return {"status": "ok"}
