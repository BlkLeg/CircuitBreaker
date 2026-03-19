"""Self-aware cluster topology — v0.2.0.

Detects Circuit Breaker's own Docker containers and groups them into a
HardwareCluster automatically. Idempotent — safe to call on every sync.
"""

import logging

from sqlalchemy.orm import Session

from app.db.models import EntityTag, HardwareCluster, HardwareClusterMember, Service, Tag

_logger = logging.getLogger(__name__)

# Detection heuristics (priority order):
# 1. com.docker.compose.project label stripped to alphanum in _CB_COMPOSE_KEYS
# 2. Container image name contains any keyword in _CB_IMAGE_KW
# 3. Container name contains any keyword in _CB_NAME_KW
_CB_COMPOSE_KEYS = {"circuitbreaker", "cb"}
_CB_IMAGE_KW = ["circuit-breaker", "circuitbreaker"]
_CB_NAME_KW = ["cb-api", "cb-worker", "cb-nats", "cb-caddy", "cb-frontend", "circuit-breaker"]
_CB_TAGS = ["self_managed", "circuitbreaker"]


def _is_cb_service(service: Service) -> bool:
    """Return True if this docker Service belongs to the CB stack."""
    labels: dict = service.docker_labels if service.docker_labels else {}

    project = labels.get("com.docker.compose.project", "").lower().replace("-", "").replace("_", "")
    if project in _CB_COMPOSE_KEYS:
        return True

    image = (service.docker_image or "").lower()
    if any(kw in image for kw in _CB_IMAGE_KW):
        return True

    name = (service.name or "").lower()
    return any(kw in name for kw in _CB_NAME_KW)


def _ensure_tag(db: Session, tag_name: str) -> Tag:
    tag = db.query(Tag).filter_by(name=tag_name).first()
    if not tag:
        tag = Tag(name=tag_name)
        db.add(tag)
        db.flush()
    return tag


def autocreate_self_cluster(db: Session) -> dict:
    """Detect CB containers and group them into a HardwareCluster.

    Creates or updates the cluster and its service members.  Returns a
    summary dict with cluster_id, member_count, and members list.
    """
    cb_services = [
        s
        for s in db.query(Service).filter(Service.is_docker_container.is_(True)).all()
        if _is_cb_service(s)
    ]

    if not cb_services:
        _logger.info("Self-cluster: no Circuit Breaker containers found.")
        return {"cluster_id": None, "member_count": 0, "members": []}

    # Find or create the CB cluster
    cluster = db.query(HardwareCluster).filter_by(name="Circuit Breaker").first()
    if not cluster:
        cluster = HardwareCluster(
            name="Circuit Breaker",
            type="docker_compose",
            icon_slug="circuitbreaker",
            description="Auto-detected Circuit Breaker cluster",
        )
        db.add(cluster)
        db.flush()
    else:
        cluster.type = "docker_compose"

    # Upsert service members (idempotent)
    for svc in cb_services:
        existing = (
            db.query(HardwareClusterMember)
            .filter_by(cluster_id=cluster.id, member_type="service", service_id=svc.id)
            .first()
        )
        if not existing:
            db.add(
                HardwareClusterMember(
                    cluster_id=cluster.id,
                    member_type="service",
                    service_id=svc.id,
                )
            )

    # Apply tags to all CB services
    for tag_name in _CB_TAGS:
        tag = _ensure_tag(db, tag_name)
        for svc in cb_services:
            exists = (
                db.query(EntityTag)
                .filter_by(entity_type="services", entity_id=svc.id, tag_id=tag.id)
                .first()
            )
            if not exists:
                db.add(EntityTag(entity_type="services", entity_id=svc.id, tag_id=tag.id))

    db.commit()
    _logger.info(
        "Self-cluster: grouped %d CB services into cluster %d.",
        len(cb_services),
        cluster.id,
    )
    return {
        "cluster_id": cluster.id,
        "member_count": len(cb_services),
        "members": [{"id": s.id, "name": s.name} for s in cb_services],
    }
