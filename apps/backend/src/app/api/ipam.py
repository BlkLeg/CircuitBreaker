"""IPAM (IP Address Management) + VLAN + Site endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.security import require_write_auth
from app.core.time import utcnow
from app.db.models import VLAN, IPAddress, Network, ScanResult, Site
from app.db.session import get_db
from app.schemas.ipam import (
    IPAddressCreate,
    IPAddressRead,
    IPAddressUpdate,
    NodeRelationCreate,
    NodeRelationRead,
    SiteCreate,
    SiteRead,
    SiteUpdate,
    VLANCreate,
    VLANRead,
    VLANUpdate,
)

_logger = logging.getLogger(__name__)

# ── IPAM ──────────────────────────────────────────────────────────────────────

ipam_router = APIRouter(tags=["ipam"])


@ipam_router.get("", response_model=list[IPAddressRead])
def list_ip_addresses(
    network_id: int | None = Query(None),
    status: str | None = Query(None),
    include_discovered: bool = Query(False),
    db: Session = Depends(get_db),
) -> Any:
    q = select(IPAddress)
    if network_id is not None:
        q = q.where(IPAddress.network_id == network_id)
    if status is not None:
        q = q.where(IPAddress.status == status)
    q = q.order_by(IPAddress.address)
    manual_rows = db.execute(q).scalars().all()

    if not include_discovered:
        return manual_rows

    # Build dedup set from manual addresses
    manual_addrs = {str(row.address) for row in manual_rows}

    # Fetch discovered hosts from merged scan results
    discovered_rows = (
        db.execute(
            select(ScanResult).where(
                ScanResult.merge_status == "merged",
                ScanResult.matched_entity_type == "hardware",
                ScanResult.ip_address.isnot(None),
            )
        )
        .scalars()
        .all()
    )

    combined: list[Any] = list(manual_rows)
    for sr in discovered_rows:
        if str(sr.ip_address) in manual_addrs:
            continue  # manual record takes precedence
        combined.append(
            IPAddressRead(
                source="discovered",
                id=None,
                address=str(sr.ip_address),
                hostname=sr.hostname,
                hardware_id=sr.matched_entity_id,
                network_id=sr.network_id,
                status="seen",
                notes=None,
                created_at=None,
                updated_at=None,
            )
        )
    return combined


@ipam_router.post("", response_model=IPAddressRead, status_code=201)
def create_ip_address(
    payload: IPAddressCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
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
        notes=payload.notes,
        allocated_at=utcnow() if payload.status == "allocated" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="ip_address_created",
        resource=f"ip_address:{row.id}",
        status="ok",
    )
    return row


@ipam_router.get("/{ip_id}", response_model=IPAddressRead)
def get_ip_address(ip_id: int, db: Session = Depends(get_db)) -> Any:
    row = db.get(IPAddress, ip_id)
    if not row:
        raise HTTPException(status_code=404, detail="IP address not found")
    return row


@ipam_router.patch("/{ip_id}", response_model=IPAddressRead)
def update_ip_address(
    ip_id: int,
    payload: IPAddressUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
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
    log_audit(
        db,
        request,
        user_id=user_id,
        action="ip_address_updated",
        resource=f"ip_address:{ip_id}",
        status="ok",
    )
    return row


@ipam_router.delete("/{ip_id}", status_code=204)
def delete_ip_address(
    ip_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    row = db.get(IPAddress, ip_id)
    if not row:
        raise HTTPException(status_code=404, detail="IP address not found")
    db.delete(row)
    db.commit()
    log_audit(
        db,
        request,
        user_id=user_id,
        action="ip_address_deleted",
        resource=f"ip_address:{ip_id}",
        status="ok",
        severity="warn",
    )


@ipam_router.post("/scan/{network_id}", response_model=list[IPAddressRead])
def scan_network_addresses(
    network_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
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
    if len(hosts) > 1022:
        raise HTTPException(status_code=400, detail="CIDR too large (max /22 = 1022 hosts)")

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
    log_audit(
        db,
        request,
        user_id=user_id,
        action="ipam_network_scanned",
        resource=f"network:{network_id}",
        status="ok",
    )
    return created


# ── VLANs ─────────────────────────────────────────────────────────────────────

vlan_router = APIRouter(tags=["vlans"])


@vlan_router.get("", response_model=list[VLANRead])
def list_vlans(db: Session = Depends(get_db)) -> Any:
    return db.execute(select(VLAN).order_by(VLAN.vlan_id)).scalars().all()


@vlan_router.post("", response_model=VLANRead, status_code=201)
def create_vlan(
    payload: VLANCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    row = VLAN(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="vlan_created",
        resource=f"vlan:{row.id}",
        status="ok",
    )
    return row


@vlan_router.get("/{vlan_pk}", response_model=VLANRead)
def get_vlan(vlan_pk: int, db: Session = Depends(get_db)) -> Any:
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    return row


@vlan_router.patch("/{vlan_pk}", response_model=VLANRead)
def update_vlan(
    vlan_pk: int,
    payload: VLANUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="vlan_updated",
        resource=f"vlan:{vlan_pk}",
        status="ok",
    )
    return row


@vlan_router.delete("/{vlan_pk}", status_code=204)
def delete_vlan(
    vlan_pk: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    row = db.get(VLAN, vlan_pk)
    if not row:
        raise HTTPException(status_code=404, detail="VLAN not found")
    db.delete(row)
    db.commit()
    log_audit(
        db,
        request,
        user_id=user_id,
        action="vlan_deleted",
        resource=f"vlan:{vlan_pk}",
        status="ok",
        severity="warn",
    )


# ── Sites ─────────────────────────────────────────────────────────────────────

site_router = APIRouter(tags=["sites"])


@site_router.get("", response_model=list[SiteRead])
def list_sites(db: Session = Depends(get_db)) -> Any:
    return db.execute(select(Site).order_by(Site.name)).scalars().all()


@site_router.post("", response_model=SiteRead, status_code=201)
def create_site(
    payload: SiteCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    row = Site(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="site_created",
        resource=f"site:{row.id}",
        status="ok",
    )
    return row


@site_router.get("/{site_id}", response_model=SiteRead)
def get_site(site_id: int, db: Session = Depends(get_db)) -> Any:
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    return row


@site_router.patch("/{site_id}", response_model=SiteRead)
def update_site(
    site_id: int,
    payload: SiteUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="site_updated",
        resource=f"site:{site_id}",
        status="ok",
    )
    return row


@site_router.delete("/{site_id}", status_code=204)
def delete_site(
    site_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    row = db.get(Site, site_id)
    if not row:
        raise HTTPException(status_code=404, detail="Site not found")
    db.delete(row)
    db.commit()
    log_audit(
        db,
        request,
        user_id=user_id,
        action="site_deleted",
        resource=f"site:{site_id}",
        status="ok",
        severity="warn",
    )


# ── Node Relations ────────────────────────────────────────────────────────────

from app.db.models import NodeRelation  # noqa: E402

node_relations_router = APIRouter(tags=["node-relations"])


@node_relations_router.get("", response_model=list[NodeRelationRead])
def list_node_relations(
    source_type: str | None = Query(None),
    source_id: int | None = Query(None),
    target_type: str | None = Query(None),
    target_id: int | None = Query(None),
    relation_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
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
    return db.execute(q.order_by(NodeRelation.id.desc())).scalars().all()


@node_relations_router.post("", response_model=NodeRelationRead, status_code=201)
def create_node_relation(
    payload: NodeRelationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    row = NodeRelation(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(
        db,
        request,
        user_id=user_id,
        action="node_relation_created",
        resource=f"node_relation:{row.id}",
        status="ok",
    )
    return row


@node_relations_router.delete("/{rel_id}", status_code=204)
def delete_node_relation(
    rel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    row = db.get(NodeRelation, rel_id)
    if not row:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(row)
    db.commit()
    log_audit(
        db,
        request,
        user_id=user_id,
        action="node_relation_deleted",
        resource=f"node_relation:{rel_id}",
        status="ok",
        severity="warn",
    )
