
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.core.time import utcnow
from app.db.models import ExternalNode, ExternalNodeNetwork, ServiceExternalNode, Network, Service, EntityTag, Tag
from app.schemas.external_nodes import (
    ExternalNodeCreate,
    ExternalNodeUpdate,
    ExternalNodeNetworkLink,
    ServiceExternalNodeLink,
)


# ── Tag helpers (reuse the entity-tag system) ────────────────────────────────

_ENTITY_TYPE = "external"


def _sync_tags(db: Session, entity_id: int, tag_names: list[str]) -> None:
    existing = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == _ENTITY_TYPE,
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
        db.add(EntityTag(entity_type=_ENTITY_TYPE, entity_id=entity_id, tag_id=tag.id))


def _get_tags(db: Session, entity_id: int) -> list[str]:
    rows = db.execute(
        select(EntityTag).where(
            EntityTag.entity_type == _ENTITY_TYPE,
            EntityTag.entity_id == entity_id,
        )
    ).scalars().all()
    return [row.tag.name for row in rows]


def _to_dict(db: Session, item: ExternalNode) -> dict:
    d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    d["tags"] = _get_tags(db, item.id)
    d["networks_count"] = len(item.network_links)
    d["services_count"] = len(item.service_links)
    return d


# ── CRUD ─────────────────────────────────────────────────────────────────────


def list_external_nodes(
    db: Session,
    *,
    environment: str | None = None,
    provider: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    stmt = select(ExternalNode)
    if environment:
        stmt = stmt.where(ExternalNode.environment == environment)
    if provider:
        stmt = stmt.where(ExternalNode.provider == provider)
    if kind:
        stmt = stmt.where(ExternalNode.kind == kind)
    if q:
        stmt = stmt.where(
            or_(
                ExternalNode.name.ilike(f"%{q}%"),
                ExternalNode.provider.ilike(f"%{q}%"),
                ExternalNode.ip_address.ilike(f"%{q}%"),
                ExternalNode.notes.ilike(f"%{q}%"),
            )
        )
    if tag:
        stmt = (
            stmt.join(EntityTag, (EntityTag.entity_type == _ENTITY_TYPE) & (EntityTag.entity_id == ExternalNode.id))
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def get_external_node(db: Session, node_id: int) -> dict:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    return _to_dict(db, item)


def create_external_node(db: Session, payload: ExternalNodeCreate) -> dict:
    item = ExternalNode(
        name=payload.name,
        provider=payload.provider,
        kind=payload.kind,
        region=payload.region,
        ip_address=payload.ip_address,
        icon_slug=payload.icon_slug,
        notes=payload.notes,
        environment=payload.environment,
    )
    db.add(item)
    db.flush()
    _sync_tags(db, item.id, payload.tags)
    db.commit()
    db.refresh(item)
    return _to_dict(db, item)


def update_external_node(db: Session, node_id: int, payload: ExternalNodeUpdate) -> dict:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"tags"}).items():
        setattr(item, field, value)
    item.updated_at = utcnow()
    if payload.tags is not None:
        _sync_tags(db, item.id, payload.tags)
    db.commit()
    db.refresh(item)
    return _to_dict(db, item)


def delete_external_node(db: Session, node_id: int) -> None:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    _sync_tags(db, item.id, [])
    db.delete(item)
    db.commit()


# ── Network relationships ────────────────────────────────────────────────────


def list_networks_for_node(db: Session, node_id: int) -> list[dict]:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    result = []
    for link in item.network_links:
        net = db.get(Network, link.network_id)
        result.append({
            "id": link.id,
            "external_node_id": link.external_node_id,
            "network_id": link.network_id,
            "link_type": link.link_type,
            "notes": link.notes,
            "network_name": net.name if net else None,
        })
    return result


def link_network(db: Session, node_id: int, payload: ExternalNodeNetworkLink) -> dict:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    net = db.get(Network, payload.network_id)
    if net is None:
        raise ValueError(f"Network {payload.network_id} not found")
    link = ExternalNodeNetwork(
        external_node_id=node_id,
        network_id=payload.network_id,
        link_type=payload.link_type,
        notes=payload.notes,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {
        "id": link.id,
        "external_node_id": link.external_node_id,
        "network_id": link.network_id,
        "link_type": link.link_type,
        "notes": link.notes,
        "network_name": net.name,
    }


def unlink_network(db: Session, relation_id: int) -> None:
    link = db.get(ExternalNodeNetwork, relation_id)
    if link is None:
        raise ValueError(f"ExternalNodeNetwork {relation_id} not found")
    db.delete(link)
    db.commit()


# ── Service relationships ────────────────────────────────────────────────────


def list_services_for_node(db: Session, node_id: int) -> list[dict]:
    item = db.get(ExternalNode, node_id)
    if item is None:
        raise ValueError(f"ExternalNode {node_id} not found")
    result = []
    for link in item.service_links:
        svc = db.get(Service, link.service_id)
        result.append({
            "id": link.id,
            "service_id": link.service_id,
            "external_node_id": link.external_node_id,
            "purpose": link.purpose,
            "service_name": svc.name if svc else None,
            "external_node_name": item.name,
        })
    return result


def link_service(db: Session, service_id: int, payload: ServiceExternalNodeLink) -> dict:
    svc = db.get(Service, service_id)
    if svc is None:
        raise ValueError(f"Service {service_id} not found")
    ext = db.get(ExternalNode, payload.external_node_id)
    if ext is None:
        raise ValueError(f"ExternalNode {payload.external_node_id} not found")
    link = ServiceExternalNode(
        service_id=service_id,
        external_node_id=payload.external_node_id,
        purpose=payload.purpose,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {
        "id": link.id,
        "service_id": link.service_id,
        "external_node_id": link.external_node_id,
        "purpose": link.purpose,
        "external_node_name": ext.name,
        "service_name": svc.name,
    }


def unlink_service(db: Session, relation_id: int) -> None:
    link = db.get(ServiceExternalNode, relation_id)
    if link is None:
        raise ValueError(f"ServiceExternalNode {relation_id} not found")
    db.delete(link)
    db.commit()
