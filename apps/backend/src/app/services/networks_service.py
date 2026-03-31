import ipaddress

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import INET as PG_INET
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import (
    ComputeNetwork,
    ComputeUnit,
    EntityTag,
    Hardware,
    HardwareNetwork,
    IPAddress,
    Network,
    NetworkPeer,
    ScanResult,
    Tag,
)
from app.schemas.networks import NetworkCreate, NetworkUpdate


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    existing = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    for et in existing:
        db.delete(et)
    db.flush()

    for name in tag_names:
        tag = db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(EntityTag(entity_type=entity_type, entity_id=entity_id, tag_id=tag.id))


def get_tags_for(db: Session, entity_type: str, entity_id: int) -> list[str]:
    rows = (
        db.execute(
            select(EntityTag).where(
                EntityTag.entity_type == entity_type,
                EntityTag.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    return [row.tag.name for row in rows]


def _to_dict(db: Session, net: Network) -> dict:
    d = {c.name: getattr(net, c.name) for c in net.__table__.columns}
    d["tags"] = get_tags_for(db, "network", net.id)
    return d


def _cidr_usable(cidr: str | None) -> int:
    """Return the number of usable host addresses in a CIDR block."""
    if not cidr:
        return 0
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net.prefixlen >= 31:
            return int(net.num_addresses)
        return int(net.num_addresses) - 2  # exclude network + broadcast
    except ValueError:
        return 0


def list_networks(
    db: Session,
    *,
    tag: str | None = None,
    vlan_id: int | None = None,
    cidr: str | None = None,
    q: str | None = None,
    gateway_hardware_id: int | None = None,
) -> list[dict]:
    stmt = select(Network)
    if vlan_id is not None:
        stmt = stmt.where(Network.vlan_id == vlan_id)
    if cidr:
        stmt = stmt.where(Network.cidr.ilike(f"%{cidr}%"))
    if q:
        stmt = stmt.where(or_(Network.name.ilike(f"%{q}%"), Network.description.ilike(f"%{q}%")))
    if gateway_hardware_id is not None:
        stmt = stmt.where(Network.gateway_hardware_id == gateway_hardware_id)
    if tag:
        stmt = (
            stmt.join(
                EntityTag,
                (EntityTag.entity_type == "network") & (EntityTag.entity_id == Network.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()

    # Batch-fetch distinct allocated IPs per network across all sources
    network_ids = [r.id for r in rows]
    if not network_ids:
        allocated_map: dict[int, int] = {}
    else:
        q1 = select(
            IPAddress.network_id.label("network_id"),
            func.host(IPAddress.address).label("ip"),
        ).where(
            IPAddress.network_id.in_(network_ids),
            IPAddress.status == "allocated",
        )
        q2 = (
            select(
                Network.id.label("network_id"),
                Hardware.ip_address.label("ip"),
            )
            .join(
                Network,
                func.cast(Hardware.ip_address, PG_INET).op("<<")(func.cast(Network.cidr, PG_INET)),
            )
            .where(
                Network.id.in_(network_ids),
                Hardware.ip_address.isnot(None),
                Network.cidr.isnot(None),
            )
        )
        q3 = (
            select(
                Network.id.label("network_id"),
                ComputeUnit.ip_address.label("ip"),
            )
            .join(
                Network,
                func.cast(ComputeUnit.ip_address, PG_INET).op("<<")(
                    func.cast(Network.cidr, PG_INET)
                ),
            )
            .where(
                Network.id.in_(network_ids),
                ComputeUnit.ip_address.isnot(None),
                Network.cidr.isnot(None),
            )
        )
        q4 = (
            select(
                Network.id.label("network_id"),
                ScanResult.ip_address.label("ip"),
            )
            .join(
                Network,
                func.cast(ScanResult.ip_address, PG_INET).op("<<")(
                    func.cast(Network.cidr, PG_INET)
                ),
            )
            .where(
                Network.id.in_(network_ids),
                Network.cidr.isnot(None),
                ScanResult.ip_address.isnot(None),
                ~ScanResult.ip_address.contains(":"),
            )
        )
        combined = union_all(q1, q2, q3, q4).subquery()
        count_rows = db.execute(
            select(
                combined.c.network_id,
                func.count(func.distinct(combined.c.ip)).label("cnt"),
            ).group_by(combined.c.network_id)
        ).all()
        allocated_map = {row.network_id: row.cnt for row in count_rows}

    results = []
    for r in rows:
        d = _to_dict(db, r)
        d["allocated_count"] = allocated_map.get(r.id, 0)
        d["total_count"] = _cidr_usable(r.cidr)
        results.append(d)
    return results


def get_network(db: Session, network_id: int) -> dict:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    d = _to_dict(db, net)
    q1 = select(func.host(IPAddress.address).label("ip")).where(
        IPAddress.network_id == network_id, IPAddress.status == "allocated"
    )
    sources = [q1]
    if net.cidr:
        _cidr_lit = literal(net.cidr)
        q2 = select(Hardware.ip_address.label("ip")).where(
            Hardware.ip_address.isnot(None),
            func.cast(Hardware.ip_address, PG_INET).op("<<")(func.cast(_cidr_lit, PG_INET)),
        )
        q3 = select(ComputeUnit.ip_address.label("ip")).where(
            ComputeUnit.ip_address.isnot(None),
            func.cast(ComputeUnit.ip_address, PG_INET).op("<<")(func.cast(_cidr_lit, PG_INET)),
        )
        q4 = select(ScanResult.ip_address.label("ip")).where(
            ScanResult.ip_address.isnot(None),
            ~ScanResult.ip_address.contains(":"),
            func.cast(ScanResult.ip_address, PG_INET).op("<<")(func.cast(_cidr_lit, PG_INET)),
        )
        sources = [q1, q2, q3, q4]
    combined = union_all(*sources).subquery()
    d["allocated_count"] = db.execute(select(func.count(func.distinct(combined.c.ip)))).scalar_one()
    d["total_count"] = _cidr_usable(net.cidr)
    return d


def create_network(db: Session, payload: NetworkCreate) -> dict:
    net = Network(
        name=payload.name,
        cidr=payload.cidr,
        vlan_id=payload.vlan_id,
        gateway=payload.gateway,
        description=payload.description,
        gateway_hardware_id=payload.gateway_hardware_id,
        icon_slug=payload.icon_slug,
        site_id=payload.site_id,
    )
    db.add(net)
    db.flush()
    _sync_tags(db, "network", net.id, payload.tags)
    db.commit()
    db.refresh(net)
    return _to_dict(db, net)


def update_network(db: Session, network_id: int, payload: NetworkUpdate) -> dict:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(net, field, value)
    net.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, "network", net.id, payload.tags)
    db.commit()
    db.refresh(net)
    return _to_dict(db, net)


def delete_network(db: Session, network_id: int) -> None:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    # Cascade-remove join-table memberships (safe to auto-remove)
    for row in (
        db.execute(select(ComputeNetwork).where(ComputeNetwork.network_id == network_id))
        .scalars()
        .all()
    ):
        db.delete(row)
    for row in (  # type: ignore[assignment]
        db.execute(select(HardwareNetwork).where(HardwareNetwork.network_id == network_id))
        .scalars()
        .all()
    ):
        db.delete(row)
    db.flush()
    _sync_tags(db, "network", net.id, [])
    db.delete(net)
    db.commit()


# ── Compute memberships ──────────────────────────────────────────────────────


def list_compute_members(db: Session, network_id: int) -> list[ComputeNetwork]:
    return list(
        db.execute(select(ComputeNetwork).where(ComputeNetwork.network_id == network_id))
        .scalars()
        .all()
    )


def add_compute_member(
    db: Session,
    network_id: int,
    compute_id: int,
    ip_address: str | None,
    connection_type: str | None = None,
) -> ComputeNetwork:
    if db.get(Network, network_id) is None:
        raise ValueError(f"Network {network_id} not found")
    cn = ComputeNetwork(
        network_id=network_id,
        compute_id=compute_id,
        ip_address=ip_address,
        connection_type=connection_type,
    )
    db.add(cn)
    db.commit()
    db.refresh(cn)
    return cn


def remove_compute_member(db: Session, network_id: int, compute_id: int) -> None:
    cn = db.execute(
        select(ComputeNetwork).where(
            ComputeNetwork.network_id == network_id,
            ComputeNetwork.compute_id == compute_id,
        )
    ).scalar_one_or_none()
    if cn is None:
        raise ValueError("Network membership not found")
    db.delete(cn)
    db.commit()


# ── Hardware memberships ─────────────────────────────────────────────────────


def list_hardware_members(db: Session, network_id: int) -> list[HardwareNetwork]:
    return list(
        db.execute(select(HardwareNetwork).where(HardwareNetwork.network_id == network_id))
        .scalars()
        .all()
    )


def add_hardware_member(
    db: Session,
    network_id: int,
    hardware_id: int,
    ip_address: str | None,
    connection_type: str | None = None,
) -> HardwareNetwork:
    from app.db.models import Network as _Network  # avoid circular at top-level

    if db.get(_Network, network_id) is None:
        raise ValueError(f"Network {network_id} not found")
    hn = HardwareNetwork(
        network_id=network_id,
        hardware_id=hardware_id,
        ip_address=ip_address,
        connection_type=connection_type,
    )
    db.add(hn)
    db.commit()
    db.refresh(hn)
    return hn


def remove_hardware_member(db: Session, network_id: int, hardware_id: int) -> None:
    hn = db.execute(
        select(HardwareNetwork).where(
            HardwareNetwork.network_id == network_id,
            HardwareNetwork.hardware_id == hardware_id,
        )
    ).scalar_one_or_none()
    if hn is None:
        raise ValueError("Hardware network membership not found")
    db.delete(hn)
    db.commit()


# ── Network peering ──────────────────────────────────────────────────────────


def list_peers(db: Session, network_id: int) -> list[NetworkPeer]:
    return list(
        db.execute(
            select(NetworkPeer).where(
                or_(NetworkPeer.network_a_id == network_id, NetworkPeer.network_b_id == network_id)
            )
        )
        .scalars()
        .all()
    )


def add_peer(
    db: Session, network_id: int, peer_id: int, connection_type: str | None = None
) -> NetworkPeer:
    if network_id == peer_id:
        raise ValueError("A network cannot peer with itself.")
    if db.get(Network, network_id) is None:
        raise ValueError(f"Network {network_id} not found.")
    if db.get(Network, peer_id) is None:
        raise ValueError(f"Network {peer_id} not found.")
    a_id, b_id = min(network_id, peer_id), max(network_id, peer_id)
    existing = db.execute(
        select(NetworkPeer).where(
            NetworkPeer.network_a_id == a_id, NetworkPeer.network_b_id == b_id
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    peer = NetworkPeer(network_a_id=a_id, network_b_id=b_id, connection_type=connection_type)
    db.add(peer)
    db.commit()
    db.refresh(peer)
    return peer


def remove_peer(db: Session, network_id: int, peer_id: int) -> None:
    a_id, b_id = min(network_id, peer_id), max(network_id, peer_id)
    peer = db.execute(
        select(NetworkPeer).where(
            NetworkPeer.network_a_id == a_id, NetworkPeer.network_b_id == b_id
        )
    ).scalar_one_or_none()
    if peer is None:
        raise ValueError("Network peer relationship not found.")
    db.delete(peer)
    db.commit()


def list_all_peers(db: Session) -> list[NetworkPeer]:
    return list(db.execute(select(NetworkPeer)).scalars().all())
