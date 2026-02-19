from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

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
)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/topology")
def get_topology(
    environment: str | None = Query(None),
    include: str = Query("hardware,compute,services,storage,networks"),
    db: Session = Depends(get_db),
):
    include_set = {i.strip() for i in include.split(",")}
    nodes: list[dict] = []
    edges: list[dict] = []

    if "hardware" in include_set:
        for hw in db.execute(select(Hardware)).scalars():
            nodes.append(
                {"id": f"hw-{hw.id}", "type": "hardware", "ref_id": hw.id, "label": hw.name, "tags": []}
            )

    if "compute" in include_set:
        q = select(ComputeUnit)
        if environment:
            q = q.where(ComputeUnit.environment == environment)
        for cu in db.execute(q).scalars():
            nodes.append(
                {
                    "id": f"cu-{cu.id}",
                    "type": "compute_unit",
                    "ref_id": cu.id,
                    "label": cu.name,
                    "tags": [],
                }
            )
            edges.append(
                {
                    "id": f"e-hw-cu-{cu.id}",
                    "source": f"hw-{cu.hardware_id}",
                    "target": f"cu-{cu.id}",
                    "relation": "hosts",
                }
            )

    if "services" in include_set:
        q = select(Service)
        if environment:
            q = q.where(Service.environment == environment)
        for svc in db.execute(q).scalars():
            nodes.append(
                {
                    "id": f"svc-{svc.id}",
                    "type": "service",
                    "ref_id": svc.id,
                    "label": svc.name,
                    "tags": [],
                }
            )
            edges.append(
                {
                    "id": f"e-cu-svc-{svc.id}",
                    "source": f"cu-{svc.compute_id}",
                    "target": f"svc-{svc.id}",
                    "relation": "runs",
                }
            )

        for dep in db.execute(select(ServiceDependency)).scalars():
            edges.append(
                {
                    "id": f"e-dep-{dep.id}",
                    "source": f"svc-{dep.service_id}",
                    "target": f"svc-{dep.depends_on_id}",
                    "relation": "depends_on",
                }
            )

    if "storage" in include_set:
        for st in db.execute(select(Storage)).scalars():
            nodes.append(
                {
                    "id": f"st-{st.id}",
                    "type": "storage",
                    "ref_id": st.id,
                    "label": st.name,
                    "tags": [],
                }
            )
        for link in db.execute(select(ServiceStorage)).scalars():
            edges.append(
                {
                    "id": f"e-ss-{link.id}",
                    "source": f"svc-{link.service_id}",
                    "target": f"st-{link.storage_id}",
                    "relation": "uses",
                }
            )

    if "networks" in include_set:
        for net in db.execute(select(Network)).scalars():
            nodes.append(
                {
                    "id": f"net-{net.id}",
                    "type": "network",
                    "ref_id": net.id,
                    "label": net.name,
                    "tags": [],
                }
            )
        for cn in db.execute(select(ComputeNetwork)).scalars():
            edges.append(
                {
                    "id": f"e-cn-{cn.id}",
                    "source": f"cu-{cn.compute_id}",
                    "target": f"net-{cn.network_id}",
                    "relation": "on_network",
                }
            )

    return {"nodes": nodes, "edges": edges}
