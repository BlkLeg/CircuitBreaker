
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeNetwork, EntityTag, HardwareNetwork, Network, Tag
from app.schemas.networks import NetworkCreate, NetworkUpdate


def _sync_tags(db: Session, entity_type: str, entity_id: int, tag_names: list[str]) -> None:
    existing = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
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
    rows = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
    return [row.tag.name for row in rows]


def _to_dict(db: Session, net: Network) -> dict:
    d = {c.name: getattr(net, c.name) for c in net.__table__.columns}
    d["tags"] = get_tags_for(db, "network", net.id)
    return d


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
        stmt = stmt.where(
            or_(Network.name.ilike(f"%{q}%"), Network.description.ilike(f"%{q}%"))
        )
    if gateway_hardware_id is not None:
        stmt = stmt.where(Network.gateway_hardware_id == gateway_hardware_id)
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == "network") & (EntityTag.entity_id == Network.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_network(db: Session, network_id: int) -> dict:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    return _to_dict(db, net)


def create_network(db: Session, payload: NetworkCreate) -> dict:
    net = Network(
        name=payload.name,
        cidr=payload.cidr,
        vlan_id=payload.vlan_id,
        gateway=payload.gateway,
        description=payload.description,
        gateway_hardware_id=payload.gateway_hardware_id,
        icon_slug=payload.icon_slug,
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
    for row in db.execute(select(ComputeNetwork).where(ComputeNetwork.network_id == network_id)).scalars().all():
        db.delete(row)
    for row in db.execute(select(HardwareNetwork).where(HardwareNetwork.network_id == network_id)).scalars().all():
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


def add_compute_member(db: Session, network_id: int, compute_id: int, ip_address: str | None) -> ComputeNetwork:
    if db.get(Network, network_id) is None:
        raise ValueError(f"Network {network_id} not found")
    cn = ComputeNetwork(network_id=network_id, compute_id=compute_id, ip_address=ip_address)
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


def add_hardware_member(db: Session, network_id: int, hardware_id: int, ip_address: str | None) -> HardwareNetwork:
    from app.db.models import Network as _Network  # avoid circular at top-level
    if db.get(_Network, network_id) is None:
        raise ValueError(f"Network {network_id} not found")
    hn = HardwareNetwork(network_id=network_id, hardware_id=hardware_id, ip_address=ip_address)
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
