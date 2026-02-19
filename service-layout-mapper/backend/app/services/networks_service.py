from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Network, ComputeNetwork
from app.schemas.networks import NetworkCreate, NetworkUpdate


def _to_dict(net: Network) -> dict:
    return {c.name: getattr(net, c.name) for c in net.__table__.columns}


def list_networks(db: Session, *, q: str | None = None) -> list[dict]:
    stmt = select(Network)
    if q:
        stmt = stmt.where(Network.name.ilike(f"%{q}%"))
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(r) for r in rows]


def get_network(db: Session, network_id: int) -> dict:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    return _to_dict(net)


def create_network(db: Session, payload: NetworkCreate) -> dict:
    net = Network(
        name=payload.name,
        cidr=payload.cidr,
        vlan_id=payload.vlan_id,
        gateway=payload.gateway,
        description=payload.description,
    )
    db.add(net)
    db.commit()
    db.refresh(net)
    return _to_dict(net)


def update_network(db: Session, network_id: int, payload: NetworkUpdate) -> dict:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(net, field, value)
    net.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(net)
    return _to_dict(net)


def delete_network(db: Session, network_id: int) -> None:
    net = db.get(Network, network_id)
    if net is None:
        raise ValueError(f"Network {network_id} not found")
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
