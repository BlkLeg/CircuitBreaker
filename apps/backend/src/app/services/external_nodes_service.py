from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.time import utcnow
from app.db.models import (
    EntityTag,
    ExternalNode,
    ExternalNodeNetwork,
    Network,
    Service,
    ServiceExternalNode,
    Tag,
)
from app.schemas.external_nodes import (
    ExternalNodeCreate,
    ExternalNodeNetworkLink,
    ExternalNodeUpdate,
    ServiceExternalNodeLink,
)
from app.schemas.inventory import PageRequest, PageResult
from app.services import entity_tags
from app.services.inventory_paging import escape_ilike, page_result, paginate_rows

# ── Tag helpers (reuse the entity-tag system) ────────────────────────────────

_ENTITY_TYPE = "external"

_EXTERNAL_SORT_COLUMNS = {
    "id": ExternalNode.id,
    "name": ExternalNode.name,
    "provider": ExternalNode.provider,
    "kind": ExternalNode.kind,
    "environment": ExternalNode.environment,
    "created_at": ExternalNode.created_at,
    "updated_at": ExternalNode.updated_at,
}


def _sync_tags(db: Session, entity_id: int, tag_names: list[str]) -> None:
    """`entity_tags.sync_tags` with this module's entity type applied."""
    entity_tags.sync_tags(db, _ENTITY_TYPE, entity_id, tag_names)


def _get_tags(db: Session, entity_id: int) -> list[str]:
    """`entity_tags.get_tags_for` with this module's entity type applied."""
    return entity_tags.get_tags_for(db, _ENTITY_TYPE, entity_id)


def _to_dict(db: Session, item: ExternalNode, tags: list[str] | None = None) -> dict:
    d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    d["tags"] = tags if tags is not None else _get_tags(db, item.id)
    d["networks_count"] = len(item.network_links)
    d["services_count"] = len(item.service_links)
    return d


# ── CRUD ─────────────────────────────────────────────────────────────────────


def _external_filtered_statement(
    *,
    environment: str | None,
    provider: str | None,
    kind: str | None,
    q: str | None,
    tag: str | None,
) -> Select[tuple[ExternalNode]]:
    statement = select(ExternalNode)
    if environment:
        statement = statement.where(ExternalNode.environment == environment)
    if provider:
        statement = statement.where(ExternalNode.provider == provider)
    if kind:
        statement = statement.where(ExternalNode.kind == kind)
    if q:
        term = f"%{escape_ilike(q)}%"
        statement = statement.where(
            or_(
                ExternalNode.name.ilike(term, escape="\\"),
                ExternalNode.provider.ilike(term, escape="\\"),
                ExternalNode.ip_address.ilike(term, escape="\\"),
                ExternalNode.notes.ilike(term, escape="\\"),
            )
        )
    if tag:
        statement = (
            statement.join(
                EntityTag,
                (EntityTag.entity_type == _ENTITY_TYPE) & (EntityTag.entity_id == ExternalNode.id),
            )
            .join(Tag, Tag.id == EntityTag.tag_id)
            .where(Tag.name == tag)
        )
    return statement


def list_external_nodes(
    db: Session,
    *,
    environment: str | None = None,
    provider: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    stmt = _external_filtered_statement(
        environment=environment, provider=provider, kind=kind, q=q, tag=tag
    )
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(db, r) for r in rows]


def list_external_nodes_page(
    db: Session,
    page: PageRequest,
    *,
    environment: str | None = None,
    provider: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    tag: str | None = None,
) -> PageResult[dict]:
    """Return a bounded external-node page without per-row tag/link queries."""
    filtered = _external_filtered_statement(
        environment=environment, provider=provider, kind=kind, q=q, tag=tag
    ).options(
        selectinload(ExternalNode.network_links),
        selectinload(ExternalNode.service_links),
    )
    rows, total = paginate_rows(
        db,
        filtered=filtered,
        page=page,
        sort_columns=_EXTERNAL_SORT_COLUMNS,
        id_column=ExternalNode.id,
    )
    tags = entity_tags.get_tags_for_many(db, _ENTITY_TYPE, [row.id for row in rows])
    items = [_to_dict(db, row, tags[row.id]) for row in rows]
    return page_result(items, total=total, page=page)


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
        result.append(
            {
                "id": link.id,
                "external_node_id": link.external_node_id,
                "network_id": link.network_id,
                "link_type": link.link_type,
                "notes": link.notes,
                "network_name": net.name if net else None,
            }
        )
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
        connection_type=payload.connection_type,
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
        result.append(
            {
                "id": link.id,
                "service_id": link.service_id,
                "external_node_id": link.external_node_id,
                "purpose": link.purpose,
                "service_name": svc.name if svc else None,
                "external_node_name": item.name,
            }
        )
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
        connection_type=payload.connection_type,
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
