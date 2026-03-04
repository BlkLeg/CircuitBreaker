
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Hardware, HardwareCluster, HardwareClusterMember
from app.schemas.clusters import HardwareClusterCreate, HardwareClusterUpdate
from app.core.time import utcnow


def _to_dict(cluster: HardwareCluster) -> dict:
    return {
        "id": cluster.id,
        "name": cluster.name,
        "icon_slug": cluster.icon_slug,
        "description": cluster.description,
        "environment": cluster.environment,
        "location": cluster.location,
        "member_count": len(cluster.members),
        "created_at": cluster.created_at,
        "updated_at": cluster.updated_at,
    }


def _member_to_dict(member: HardwareClusterMember) -> dict:
    return {
        "id": member.id,
        "cluster_id": member.cluster_id,
        "hardware_id": member.hardware_id,
        "role": member.role,
        "hardware_name": member.hardware.name if member.hardware else None,
    }


def list_clusters(db: Session, *, environment: str | None = None) -> list[dict]:
    stmt = select(HardwareCluster)
    if environment:
        stmt = stmt.where(HardwareCluster.environment == environment)
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(r) for r in rows]


def get_cluster(db: Session, cluster_id: int) -> dict:
    cluster = db.get(HardwareCluster, cluster_id)
    if cluster is None:
        raise ValueError(f"Hardware cluster {cluster_id} not found")
    return _to_dict(cluster)


def create_cluster(db: Session, payload: HardwareClusterCreate) -> dict:
    cluster = HardwareCluster(
        name=payload.name,
        icon_slug=payload.icon_slug,
        description=payload.description,
        environment=payload.environment,
        location=payload.location,
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return _to_dict(cluster)


def update_cluster(db: Session, cluster_id: int, payload: HardwareClusterUpdate) -> dict:
    cluster = db.get(HardwareCluster, cluster_id)
    if cluster is None:
        raise ValueError(f"Hardware cluster {cluster_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cluster, field, value)
    cluster.updated_at = utcnow()
    db.commit()
    db.refresh(cluster)
    return _to_dict(cluster)


def delete_cluster(db: Session, cluster_id: int) -> None:
    cluster = db.get(HardwareCluster, cluster_id)
    if cluster is None:
        raise ValueError(f"Hardware cluster {cluster_id} not found")
    db.delete(cluster)
    db.commit()


# ── Members ──────────────────────────────────────────────────────────────────


def list_members(db: Session, cluster_id: int) -> list[dict]:
    if db.get(HardwareCluster, cluster_id) is None:
        raise ValueError(f"Hardware cluster {cluster_id} not found")
    rows = db.execute(
        select(HardwareClusterMember).where(HardwareClusterMember.cluster_id == cluster_id)
    ).scalars().all()
    return [_member_to_dict(m) for m in rows]


def add_member(db: Session, cluster_id: int, hardware_id: int, role: str | None = None) -> dict:
    if db.get(HardwareCluster, cluster_id) is None:
        raise ValueError(f"Hardware cluster {cluster_id} not found")
    if db.get(Hardware, hardware_id) is None:
        raise ValueError(f"Hardware {hardware_id} not found")
    member = HardwareClusterMember(cluster_id=cluster_id, hardware_id=hardware_id, role=role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return _member_to_dict(member)


def update_member(db: Session, cluster_id: int, member_id: int, role: str | None) -> dict:
    member = db.execute(
        select(HardwareClusterMember).where(
            HardwareClusterMember.id == member_id,
            HardwareClusterMember.cluster_id == cluster_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise ValueError(f"Member {member_id} not found in cluster {cluster_id}")
    member.role = role
    db.commit()
    db.refresh(member)
    return _member_to_dict(member)


def remove_member(db: Session, cluster_id: int, member_id: int) -> None:
    member = db.execute(
        select(HardwareClusterMember).where(
            HardwareClusterMember.id == member_id,
            HardwareClusterMember.cluster_id == cluster_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise ValueError(f"Member {member_id} not found in cluster {cluster_id}")
    db.delete(member)
    db.commit()


def list_for_hardware(db: Session, hardware_id: int) -> list[dict]:
    """Return all clusters this hardware belongs to, with role info."""
    rows = db.execute(
        select(HardwareClusterMember).where(HardwareClusterMember.hardware_id == hardware_id)
    ).scalars().all()
    result = []
    for m in rows:
        cluster = db.get(HardwareCluster, m.cluster_id)
        result.append({
            "membership_id": m.id,
            "role": m.role,
            "cluster": {
                "id": cluster.id,
                "name": cluster.name,
                "icon_slug": cluster.icon_slug,
                "environment": cluster.environment,
                "location": cluster.location,
                "description": cluster.description,
            } if cluster else None,
        })
    return result
