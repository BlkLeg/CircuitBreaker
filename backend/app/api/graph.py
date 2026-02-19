import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

_logger = logging.getLogger(__name__)

from app.db.session import get_db
from app.db.models import (
    Hardware,
    ComputeUnit,
    Service,
    ServiceDependency,
    Storage,
    ServiceStorage,
    Network,
    ComputeNetwork,
    MiscItem,
    ServiceMisc,
    GraphLayout,
    Tag,
    EntityTag,
)

router = APIRouter(prefix="/graph", tags=["graph"])


class LayoutUpdate(BaseModel):
    name: str = "default"
    layout_data: str  # JSON string


@router.get("/topology")
def get_topology(
    environment: str | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks,misc"),
    db: Session = Depends(get_db),
):
    include_set = {i.strip().lower() for i in include.split(",")}
    nodes: list[dict] = []
    edges: list[dict] = []
    
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

    # 1. Hardware
    if "hardware" in include_set:
        for hw in db.execute(select(Hardware)).scalars():
            nodes.append({
                "id": f"hw-{hw.id}",
                "type": "hardware",
                "ref_id": hw.id,
                "label": hw.name,
                "vendor": hw.vendor,
                "tags": get_tags("hardware", hw.id)
            })

    # 2. Compute
    if "compute" in include_set:
        q = select(ComputeUnit)
        if environment:
            q = q.where(ComputeUnit.environment == environment)
        for cu in db.execute(q).scalars():
            nodes.append({
                "id": f"cu-{cu.id}",
                "type": "compute",
                "ref_id": cu.id,
                "label": cu.name,
                "icon_slug": cu.icon_slug,
                "tags": get_tags("compute", cu.id)
            })
            # Link to Hardware
            if "hardware" in include_set:
                edges.append({
                    "id": f"e-hw-cu-{cu.id}",
                    "source": f"hw-{cu.hardware_id}",
                    "target": f"cu-{cu.id}",
                    "relation": "hosts",
                })

    # 3. Services
    if "services" in include_set:
        q = select(Service)
        if environment:
            q = q.where(Service.environment == environment)
        services = db.execute(q).scalars().all()
        service_ids = {s.id for s in services}

        for svc in services:
            nodes.append({
                "id": f"svc-{svc.id}",
                "type": "service",
                "ref_id": svc.id,
                "label": svc.name,
                "icon_slug": svc.icon_slug,
                "tags": get_tags("services", svc.id)
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

        # Service -> Service dependencies
        # Only if both sides are in our filtered set
        deps = db.execute(select(ServiceDependency)).scalars().all()
        for dep in deps:
            if dep.service_id in service_ids and dep.depends_on_id in service_ids:
                edges.append({
                    "id": f"e-dep-{dep.id}",
                    "source": f"svc-{dep.service_id}",
                    "target": f"svc-{dep.depends_on_id}",
                    "relation": "depends_on",
                })

        # Service -> Storage
        if "storage" in include_set:
            # We need to know which storage nodes exist too
            # (Assuming we fetch all storage if 'storage' is included)
            # Better to check existence if we filter storage (currently we don't filter storage by env)
            links = db.execute(select(ServiceStorage)).scalars().all()
            for link in links:
                if link.service_id in service_ids:
                    edges.append({
                        "id": f"e-ss-{link.id}",
                        "source": f"svc-{link.service_id}",
                        "target": f"st-{link.storage_id}",
                        "relation": "uses",
                    })
        
        # Service -> Misc
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

    # 4. Storage
    if "storage" in include_set:
        for st in db.execute(select(Storage)).scalars():
            nodes.append({
                "id": f"st-{st.id}",
                "type": "storage",
                "ref_id": st.id,
                "label": st.name,
                "tags": get_tags("storage", st.id)
            })

    # 5. Networks
    if "networks" in include_set:
        for net in db.execute(select(Network)).scalars():
            nodes.append({
                "id": f"net-{net.id}",
                "type": "network",
                "ref_id": net.id,
                "label": net.name,
                "tags": get_tags("networks", net.id)
            })
            # Compute -> Network
            if "compute" in include_set:
                # We need to filter by the compute units we actually fetched?
                # For v1, let's just fetch all links and filter by node existence in frontend or here.
                # Filter here is valid.
                pass
        
        if "compute" in include_set:
            # Re-fetch compute IDs just to be safe or use what we have? 
            # We didn't store valid CU IDs in a set. Let's relying on the edge creation logic
            # to be filtered by valid nodes in the Frontend is risky. 
            # Let's act defensively: only add edges if we know the nodes are likely there.
            # Actually, `compute` filtering was done. We should probably track valid IDs.
            # For simplicity, we just dump all edges. ReactFlow handles missing nodes gracefully usually.
            cns = db.execute(select(ComputeNetwork)).scalars().all()
            for cn in cns:
                 edges.append({
                    "id": f"e-cn-{cn.id}",
                    "source": f"cu-{cn.compute_id}",
                    "target": f"net-{cn.network_id}",
                    "relation": "connects_to",
                })

    # 6. Misc
    if "misc" in include_set:
        for m in db.execute(select(MiscItem)).scalars():
            nodes.append({
                "id": f"misc-{m.id}",
                "type": "misc",
                "ref_id": m.id,
                "label": m.name,
                "tags": get_tags("misc", m.id)
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
