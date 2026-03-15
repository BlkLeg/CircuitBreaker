"""IPAM (IP Address Management) + VLAN + Site endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.core.time import utcnow
from app.db.models import (
    VLAN,
    Hardware,
    IPAddress,
    IPConflict,
    IPReservationQueue,
    Network,
    NodeRelation,
    Site,
    VLANTrunk,
)
from app.db.session import get_db
from app.schemas.ipam import (
    IPAddressCreate,
    IPAddressRead,
    IPAddressUpdate,
    IPConflictRead,
    IPConflictResolve,
    IPReservationQueueRead,
    NodeRelationCreate,
    NodeRelationRead,
    NodeRelationUpdate,
    SiteCreate,
    SiteRead,
    SiteUpdate,
    VLANCreate,
    VLANRead,
    VLANTrunkCreate,
    VLANTrunkRead,
    VLANUpdate,
)

_logger = logging.getLogger(__name__)

# ── IPAM ──────────────────────────────────────────────────────────────────────

ipam_router = APIRouter(tags=["ipam"])


@ipam_router.get("", response_model=list[IPAddressRead])
def list_ip_addresses(
    network_id: int | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(IPAddress)
    if network_id is not None:
        q = q.where(IPAddress.network_id == network_id)
    if status is not None:
        q = q.where(IPAddress.status == status)
    q = q.order_by(IPAddress.address)
    return db.execute(q).scalars().all()


@ipam_router.post("", response_model=IPAddressRead, status_code=201)
def create_ip_address(
    payload: IPAddressCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    existing = db.execute(
        select(IPAddress).where(IPAddress.address == payload.address)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Address {payload.address} already tracked")

    row = IPAddress(
        address=payload.address,
        network_id=payload.network_id,
        status=payload.status,
        hardware_id=payload.hardware_id,
        service_id=payload.service_id,
        hostname=payload.hostname,
        allocated_at=utcnow() if payload.status == "allocated" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@ipam_router.post("/scan/{network_id}", response_model=list[IPAddressRead])
def scan_network_addresses(
    network_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Auto-populate IPAM entries from a network's CIDR range."""
    import ipaddress as _ip

    net = db.get(Network, network_id)
    if not net or not net.cidr:
        raise HTTPException(status_code=404, detail="Network not found or has no CIDR")

    try:
        network = _ip.ip_network(net.cidr, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CIDR: {exc}") from exc

    hosts = list(network.hosts())
    if len(hosts) > 1024:
        raise HTTPException(status_code=400, detail="CIDR too large (max /22 = 1024 hosts)")

    created: list[IPAddress] = []
    for host in hosts:
        addr_str = str(host)
        existing = db.execute(
            select(IPAddress).where(IPAddress.address == addr_str)
        ).scalar_one_or_none()
        if existing:
            continue
        row = IPAddress(
            address=addr_str,
            network_id=network_id,
            tenant_id=net.tenant_id,
            status="free",
        )
        db.add(row)
        created.append(row)

    db.commit()
    for r in created:
        db.refresh(r)
    return created


# ── Reservation Queue ─────────────────────────────────────────────────────
# NOTE: Literal paths MUST be registered before /{ip_id} to avoid path capture.


@ipam_router.get("/reservation-queue", response_model=list[IPReservationQueueRead])
def list_reservation_queue(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(IPReservationQueue)
    if status:
        q = q.where(IPReservationQueue.status == status)
    q = q.order_by(IPReservationQueue.created_at.desc())
    return db.execute(q).scalars().all()


@ipam_router.post("/reservation-queue/{entry_id}/approve", response_model=IPAddressRead)
def approve_reservation(entry_id: int, db=Depends(get_db), _=Depends(require_write_auth)):
    entry = db.get(IPReservationQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    if entry.status != "pending":
        raise HTTPException(409, f"Entry already {entry.status}")
    from app.services.ip_reservation import auto_reserve_ip

    result = auto_reserve_ip(
        db, entry.hardware_id, str(entry.ip_address), entry.hostname, entry.tenant_id
    )
    if result is None:
        raise HTTPException(409, "IP conflict — cannot approve")
    entry.status = "approved"
    entry.reviewed_at = utcnow()
    db.commit()
    db.refresh(result)
    return result


@ipam_router.post("/reservation-queue/{entry_id}/reject", status_code=204)
def reject_reservation(entry_id: int, db=Depends(get_db), _=Depends(require_write_auth)):
    entry = db.get(IPReservationQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    entry.status = "rejected"
    entry.reviewed_at = utcnow()
    db.commit()


# ── Conflicts ──────────────────────────────────────────────────────────────


@ipam_router.get("/conflicts", response_model=list[IPConflictRead])
def list_conflicts(
    status: str | None = Query(None),
    network_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(IPConflict)
    if status:
        q = q.where(IPConflict.status == status)
    q = q.order_by(IPConflict.created_at.desc())
    return db.execute(q).scalars().all()


@ipam_router.get("/conflicts/summary")
def conflict_summary(db: Session = Depends(get_db)):
    from sqlalchemy import func

    rows = db.execute(select(IPConflict.status, func.count()).group_by(IPConflict.status)).all()
    return {row[0]: row[1] for row in rows}


@ipam_router.post("/conflicts/{conflict_id}/resolve", response_model=IPConflictRead)
def resolve_conflict_endpoint(
    conflict_id: int,
    payload: IPConflictResolve,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    from app.services.ip_reservation import resolve_conflict

    try:
        result = resolve_conflict(
            db, conflict_id, payload.resolution, payload.user_id, payload.notes
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    db.commit()
    db.refresh(result)
    return result


@ipam_router.post("/conflicts/{conflict_id}/dismiss", status_code=204)
def dismiss_conflict(conflict_id: int, db=Depends(get_db), _=Depends(require_write_auth)):
    c = db.get(IPConflict, conflict_id)
    if not c:
        raise HTTPException(404, "Conflict not found")
    c.status = "dismissed"
    c.resolved_at = utcnow()
    db.commit()


# ── IP Address by ID (MUST be after all literal /ipam/* paths) ────────────


@ipam_router.get("/{ip_id}", response_model=IPAddressRead)
def get_ip_address(ip_id: int, db: Session = Depends(get_db)):
    row = db.get(IPAddress, ip_id)
    if not row:
        raise HTTPException(status_code=404, detail="IP address not found")
    return row


@ipam_router.patch("/{ip_id}", response_model=IPAddressRead)
def update_ip_address(
    ip_id: int,
    payload: IPAddressUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(IPAddress, ip_id)
    if not row:
        raise HTTPException(status_code=404, detail="IP address not found")
    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(row, k, v)
    if "status" in update_data and update_data["status"] == "allocated" and not row.allocated_at:
        row.allocated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


@ipam_router.delete("/{ip_id}", status_code=204)
def delete_ip_address(
    ip_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(IPAddress, ip_id)
    if not row:
        raise HTTPException(status_code=404, detail="IP address not found")
    db.delete(row)
    db.commit()


# ── VLANs ─────────────────────────────────────────────────────────────────────

vlan_router = APIRouter(tags=["vlans"])


@vlan_router.get("", response_model=list[VLANRead])
def list_vlans(db: Session = Depends(get_db)):
    return db.execute(select(VLAN).order_by(VLAN.vlan_id)).scalars().all()


@vlan_router.post("", response_model=VLANRead, status_code=201)
def create_vlan(
    payload: VLANCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = VLAN(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@vlan_router.get("/matrix")
def vlan_matrix(db: Session = Depends(get_db)):
    """VLAN-to-hardware matrix: which hardware has trunk membership on which VLANs."""
    vlans = db.execute(select(VLAN).order_by(VLAN.vlan_id)).scalars().all()
    hardware = db.execute(select(Hardware).order_by(Hardware.name)).scalars().all()
    trunks = db.execute(select(VLANTrunk)).scalars().all()

    trunk_map: dict[tuple[int, int], str] = {}
    for t in trunks:
        trunk_map[(t.vlan_id, t.hardware_id)] = "tagged" if t.tagged else "untagged"

    return {
        "vlans": [{"id": v.id, "vlan_id": v.vlan_id, "name": v.name} for v in vlans],
        "hardware": [{"id": h.id, "name": h.name} for h in hardware],
        "matrix": {f"{v_id},{h_id}": mode for (v_id, h_id), mode in trunk_map.items()},
    }


@vlan_router.get("/{vlan_pk}", response_model=VLANRead)
def get_vlan(vlan_pk: int, db: Session = Depends(get_db)):
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    return row


@vlan_router.patch("/{vlan_pk}", response_model=VLANRead)
def update_vlan(
    vlan_pk: int,
    payload: VLANUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@vlan_router.delete("/{vlan_pk}", status_code=204)
def delete_vlan(
    vlan_pk: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    db.delete(row)
    db.commit()


@vlan_router.get("/{vlan_pk}/networks")
def get_vlan_networks(vlan_pk: int, db: Session = Depends(get_db)):
    """Get networks associated with this VLAN via the vlan_pk FK."""
    vlan = db.get(VLAN, vlan_pk)
    if not vlan:
        raise HTTPException(status_code=404, detail="VLAN not found")
    nets = db.execute(select(Network).where(Network.vlan_pk == vlan_pk)).scalars().all()
    return [{"id": n.id, "name": n.name, "cidr": n.cidr} for n in nets]


@vlan_router.post("/{vlan_pk}/networks/{network_id}", status_code=204)
def associate_vlan_network(
    vlan_pk: int,
    network_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Associate a network with this VLAN."""
    vlan = db.get(VLAN, vlan_pk)
    if not vlan:
        raise HTTPException(status_code=404, detail="VLAN not found")
    net = db.get(Network, network_id)
    if not net:
        raise HTTPException(status_code=404, detail="Network not found")
    net.vlan_pk = vlan_pk
    net.vlan_id = vlan.vlan_id
    db.commit()


@vlan_router.delete("/{vlan_pk}/networks/{network_id}", status_code=204)
def dissociate_vlan_network(
    vlan_pk: int,
    network_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    """Remove network association from this VLAN."""
    net = db.get(Network, network_id)
    if not net:
        raise HTTPException(status_code=404, detail="Network not found")
    if net.vlan_pk == vlan_pk:
        net.vlan_pk = None
    db.commit()


@vlan_router.get("/{vlan_pk}/hardware")
def get_vlan_hardware(vlan_pk: int, db: Session = Depends(get_db)):
    """Get hardware with trunk membership for this VLAN."""
    trunks = db.execute(select(VLANTrunk).where(VLANTrunk.vlan_id == vlan_pk)).scalars().all()
    result = []
    for t in trunks:
        hw = db.get(Hardware, t.hardware_id)
        if hw:
            result.append(
                {
                    "trunk_id": t.id,
                    "hardware_id": hw.id,
                    "hardware_name": hw.name,
                    "port_label": t.port_label,
                    "tagged": t.tagged,
                }
            )
    return result


# ── Sites ─────────────────────────────────────────────────────────────────────

site_router = APIRouter(tags=["sites"])


@site_router.get("", response_model=list[SiteRead])
def list_sites(db: Session = Depends(get_db)):
    return db.execute(select(Site).order_by(Site.name)).scalars().all()


@site_router.post("", response_model=SiteRead, status_code=201)
def create_site(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = Site(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@site_router.get("/{site_id}", response_model=SiteRead)
def get_site(site_id: int, db: Session = Depends(get_db)):
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    return row


@site_router.patch("/{site_id}", response_model=SiteRead)
def update_site(
    site_id: int,
    payload: SiteUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@site_router.delete("/{site_id}", status_code=204)
def delete_site(
    site_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    db.delete(row)
    db.commit()


# ── Node Relations ────────────────────────────────────────────────────────────

node_relations_router = APIRouter(tags=["node-relations"])


@node_relations_router.get("", response_model=list[NodeRelationRead])
def list_node_relations(
    source_type: str | None = Query(None),
    source_id: int | None = Query(None),
    target_type: str | None = Query(None),
    target_id: int | None = Query(None),
    relation_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(NodeRelation)
    if source_type:
        q = q.where(NodeRelation.source_type == source_type)
    if source_id is not None:
        q = q.where(NodeRelation.source_id == source_id)
    if target_type:
        q = q.where(NodeRelation.target_type == target_type)
    if target_id is not None:
        q = q.where(NodeRelation.target_id == target_id)
    if relation_type:
        q = q.where(NodeRelation.relation_type == relation_type)
    return db.execute(q.order_by(NodeRelation.created_at.desc())).scalars().all()


@node_relations_router.post("", response_model=NodeRelationRead, status_code=201)
def create_node_relation(
    payload: NodeRelationCreate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = NodeRelation(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@node_relations_router.patch("/{rel_id}", response_model=NodeRelationRead)
def update_node_relation(
    rel_id: int,
    payload: NodeRelationUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(NodeRelation, rel_id)
    if not row:
        raise HTTPException(status_code=404, detail="Relation not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return row


@node_relations_router.delete("/{rel_id}", status_code=204)
def delete_node_relation(
    rel_id: int,
    db: Session = Depends(get_db),
    _=Depends(require_write_auth),
):
    row = db.get(NodeRelation, rel_id)
    if not row:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(row)
    db.commit()


# ── VLAN Trunks ───────────────────────────────────────────────────────────────

trunk_router = APIRouter(tags=["vlan-trunks"])


@trunk_router.get("", response_model=list[VLANTrunkRead])
def list_trunks(
    hardware_id: int | None = Query(None),
    vlan_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(VLANTrunk)
    if hardware_id is not None:
        q = q.where(VLANTrunk.hardware_id == hardware_id)
    if vlan_id is not None:
        q = q.where(VLANTrunk.vlan_id == vlan_id)
    return db.execute(q).scalars().all()


@trunk_router.post("", response_model=VLANTrunkRead, status_code=201)
def create_trunk(payload: VLANTrunkCreate, db=Depends(get_db), _=Depends(require_write_auth)):
    row = VLANTrunk(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@trunk_router.delete("/{trunk_id}", status_code=204)
def delete_trunk(trunk_id: int, db=Depends(get_db), _=Depends(require_write_auth)):
    row = db.get(VLANTrunk, trunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="Trunk not found")
    db.delete(row)
    db.commit()


# ── DHCP ──────────────────────────────────────────────────────────────────────

from app.db.models import DHCPLease, DHCPPool  # noqa: E402
from app.schemas.ipam import (  # noqa: E402
    DHCPLeaseImport,
    DHCPLeaseRead,
    DHCPPoolCreate,
    DHCPPoolRead,
    DHCPPoolUpdate,
)

dhcp_router = APIRouter(tags=["dhcp"])


@dhcp_router.get("/pools", response_model=list[DHCPPoolRead])
def list_dhcp_pools(db: Session = Depends(get_db)):
    return db.execute(select(DHCPPool).order_by(DHCPPool.name)).scalars().all()


@dhcp_router.post("/pools", response_model=DHCPPoolRead, status_code=201)
def create_dhcp_pool(payload: DHCPPoolCreate, db=Depends(get_db), _=Depends(require_write_auth)):
    from app.services.dhcp_service import create_pool

    try:
        pool = create_pool(
            db,
            payload.name,
            payload.network_id,
            payload.start_ip,
            payload.end_ip,
            payload.lease_duration_seconds,
            payload.tenant_id,
        )
        db.commit()
        db.refresh(pool)
        return pool
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@dhcp_router.get("/pools/{pool_id}", response_model=DHCPPoolRead)
def get_dhcp_pool(pool_id: int, db=Depends(get_db)):
    pool = db.get(DHCPPool, pool_id)
    if not pool:
        raise HTTPException(404, "Pool not found")
    return pool


@dhcp_router.patch("/pools/{pool_id}", response_model=DHCPPoolRead)
def update_dhcp_pool(
    pool_id: int, payload: DHCPPoolUpdate, db=Depends(get_db), _=Depends(require_write_auth)
):
    pool = db.get(DHCPPool, pool_id)
    if not pool:
        raise HTTPException(404, "Pool not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(pool, k, v)
    db.commit()
    db.refresh(pool)
    return pool


@dhcp_router.delete("/pools/{pool_id}", status_code=204)
def delete_dhcp_pool(pool_id: int, db=Depends(get_db), _=Depends(require_write_auth)):
    pool = db.get(DHCPPool, pool_id)
    if not pool:
        raise HTTPException(404, "Pool not found")
    db.delete(pool)
    db.commit()


@dhcp_router.get("/pools/{pool_id}/leases", response_model=list[DHCPLeaseRead])
def list_pool_leases(pool_id: int, db=Depends(get_db)):
    return (
        db.execute(
            select(DHCPLease).where(DHCPLease.pool_id == pool_id).order_by(DHCPLease.ip_address)
        )
        .scalars()
        .all()
    )


@dhcp_router.post("/pools/{pool_id}/leases/import")
def import_pool_leases(
    pool_id: int, payload: DHCPLeaseImport, db=Depends(get_db), _=Depends(require_write_auth)
):
    from app.services.dhcp_service import import_leases

    count = import_leases(db, pool_id, [lease.model_dump() for lease in payload.leases])
    db.commit()
    return {"imported": count}


@dhcp_router.get("/pools/{pool_id}/utilization")
def pool_utilization(pool_id: int, db=Depends(get_db)):
    from app.services.dhcp_service import get_pool_utilization

    try:
        return get_pool_utilization(db, pool_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


# ── Subnet ────────────────────────────────────────────────────────────────────

from pydantic import BaseModel as _PydanticBase  # noqa: E402

subnet_router = APIRouter(tags=["subnet"])


@subnet_router.get("/calculate")
def calculate_subnet(cidr: str = Query(...), db=Depends(get_db)):
    from app.services.subnet_service import calculate_subnet as _calc

    try:
        return _calc(cidr)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@subnet_router.get("/networks/{network_id}/utilization")
def network_utilization(network_id: int, db=Depends(get_db)):
    from app.services.subnet_service import get_ip_utilization

    try:
        return get_ip_utilization(db, network_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@subnet_router.get("/networks/{network_id}/heatmap")
def network_heatmap(network_id: int, db=Depends(get_db)):
    from app.services.subnet_service import get_ip_heatmap

    try:
        return get_ip_heatmap(db, network_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


class _SplitRequest(_PydanticBase):
    cidr: str
    new_prefix: int


@subnet_router.post("/split")
def split_preview(payload: _SplitRequest):
    from app.services.subnet_service import suggest_split

    try:
        return {"subnets": suggest_split(payload.cidr, payload.new_prefix)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
