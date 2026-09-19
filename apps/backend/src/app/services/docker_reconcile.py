"""Pure planning and transactional, source-scoped Docker reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ComputeUnit, DockerSource, DockerSyncRun, Network, Service
from app.schemas.docker import (
    DockerContainerObservation,
    DockerEnumeration,
    DockerNetworkObservation,
    DockerReconciliationResult,
)
from app.services.docker_sources import clear_deleted_parent


class StaleDockerRun(RuntimeError):
    """A run no longer owns the source revision or execution order."""


@dataclass(frozen=True, slots=True)
class ExistingContainer:
    id: int
    native_id: str
    workload_key: str | None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class ExistingNetwork:
    id: int
    native_id: str


@dataclass(slots=True)
class DockerReconciliationPlan:
    create_containers: list[DockerContainerObservation] = field(default_factory=list)
    update_containers: list[tuple[int, DockerContainerObservation]] = field(default_factory=list)
    stop_container_ids: list[int] = field(default_factory=list)
    create_networks: list[DockerNetworkObservation] = field(default_factory=list)
    update_networks: list[tuple[int, DockerNetworkObservation]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def plan_reconciliation(
    existing_containers: list[ExistingContainer],
    existing_networks: list[ExistingNetwork],
    enumeration: DockerEnumeration,
) -> DockerReconciliationPlan:
    """Build a deterministic delta; names are never treated as identities."""
    plan = DockerReconciliationPlan()
    by_native = {item.native_id: item for item in existing_containers}
    by_workload: dict[str, list[ExistingContainer]] = {}
    for item in existing_containers:
        if item.workload_key:
            by_workload.setdefault(item.workload_key, []).append(item)
    matched_ids: set[int] = set()
    for observed in enumeration.containers:
        exact = by_native.get(observed.native_id)
        if exact is not None:
            matched_ids.add(exact.id)
            plan.update_containers.append((exact.id, observed))
            continue
        candidates = by_workload.get(observed.workload_key, []) if observed.workload_key else []
        unmatched = [candidate for candidate in candidates if candidate.id not in matched_ids]
        if len(unmatched) == 1:
            matched_ids.add(unmatched[0].id)
            plan.update_containers.append((unmatched[0].id, observed))
        elif len(unmatched) > 1:
            plan.conflicts.append(f"ambiguous_workload:{observed.workload_key}")
            # The observation proves that one of these workloads still exists,
            # but not which one. Preserve every candidate rather than turning
            # ambiguity into destructive absence inference.
            matched_ids.update(candidate.id for candidate in unmatched)
        else:
            plan.create_containers.append(observed)
    if enumeration.containers_complete:
        plan.stop_container_ids = [
            item.id
            for item in existing_containers
            if item.id not in matched_ids and item.status != "stopped"
        ]

    networks_by_native = {item.native_id: item for item in existing_networks}
    for network_observation in enumeration.networks:
        existing = networks_by_native.get(network_observation.native_id)
        if existing is None:
            plan.create_networks.append(network_observation)
        else:
            plan.update_networks.append((existing.id, network_observation))
    return plan


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "container"


def _unique_slug(db: Session, name: str, native_id: str) -> str:
    base = _slugify(name)
    candidate = base
    counter = 1
    while db.query(Service.id).filter(Service.slug == candidate).first() is not None:
        suffix = native_id[:8] if counter == 1 else f"{native_id[:8]}-{counter}"
        candidate = f"{base}-{suffix}"
        counter += 1
    return candidate


def _status(value: str) -> str:
    return {
        "running": "running",
        "healthy": "running",
        "starting": "degraded",
        "restarting": "degraded",
        "exited": "stopped",
        "paused": "stopped",
        "dead": "stopped",
        "created": "stopped",
        "removing": "stopped",
    }.get(value.lower(), "unknown")


def _set_parent(service: Service, source: DockerSource, db: Session) -> None:
    if service.docker_parent_provenance == "manual":
        return
    service.compute_id = source.parent_id if source.parent_type == "compute" else None
    if source.parent_type == "hardware":
        service.hardware_id = source.parent_id
    elif source.parent_type == "compute" and source.parent_id is not None:
        compute = db.get(ComputeUnit, source.parent_id)
        service.hardware_id = compute.hardware_id if compute is not None else None
    else:
        service.hardware_id = None
    service.docker_parent_provenance = "automatic" if source.parent_id is not None else "unresolved"


def _apply_container(
    service: Service,
    observation: DockerContainerObservation,
    source: DockerSource,
    seen_at: datetime,
    db: Session,
) -> None:
    service.name = observation.name
    service.docker_container_id = observation.native_id
    service.docker_image = observation.image
    service.docker_labels = observation.labels
    service.docker_workload_key = observation.workload_key
    service.docker_network_ids = observation.network_ids
    service.docker_source_id = source.id
    service.is_docker_container = True
    service.status = _status(observation.status)
    service.ip_address = observation.ip_address
    service.docker_last_seen_at = seen_at
    service.updated_at = seen_at
    _set_parent(service, source, db)


def apply_reconciliation(
    db: Session,
    source_id: int,
    run_id: str,
    lease_token: str,
    enumeration: DockerEnumeration,
) -> DockerReconciliationResult:
    """Revalidate ownership, apply the source delta, and finish atomically."""
    source = db.query(DockerSource).filter(DockerSource.id == source_id).with_for_update().one()
    run = (
        db.query(DockerSyncRun)
        .filter(DockerSyncRun.id == run_id, DockerSyncRun.source_id == source_id)
        .with_for_update()
        .one()
    )
    clear_deleted_parent(db, source)
    if (
        run.status != "running"
        or run.lease_token != lease_token
        or run.source_revision != source.revision
        or db.query(DockerSyncRun.id)
        .filter(
            DockerSyncRun.source_id == source_id,
            DockerSyncRun.created_at > run.created_at,
        )
        .first()
        is not None
    ):
        raise StaleDockerRun("Docker run no longer owns this source revision.")

    source.last_attempt_at = enumeration.completed_at
    run.containers_complete = enumeration.containers_complete
    run.networks_complete = enumeration.networks_complete
    run.containers_observed = len(enumeration.containers)
    run.networks_observed = len(enumeration.networks)
    run.reason_code = enumeration.reason_code
    run.safe_message = enumeration.safe_message

    if enumeration.outcome == "failed":
        run.status = "failed"
        run.completed_at = enumeration.completed_at
        run.lease_token = None
        run.lease_expires_at = None
        db.flush()
        return DockerReconciliationResult()

    observed_container_ids = [item.native_id for item in enumeration.containers]
    # Adopt only a legacy row with the exact immutable daemon ID. Unseen legacy
    # rows remain quarantined and cannot be stopped by this source.
    if observed_container_ids:
        legacy_services = (
            db.query(Service)
            .filter(
                Service.docker_source_id.is_(None),
                Service.docker_container_id.in_(observed_container_ids),
                Service.is_docker_container.is_(True),
            )
            .all()
        )
        for service in legacy_services:
            service.docker_source_id = source.id
    observed_network_ids = [item.native_id for item in enumeration.networks]
    if observed_network_ids:
        legacy_networks = (
            db.query(Network)
            .filter(
                Network.docker_source_id.is_(None),
                Network.docker_network_id.in_(observed_network_ids),
                Network.is_docker_network.is_(True),
            )
            .all()
        )
        for network in legacy_networks:
            network.docker_source_id = source.id
    db.flush()

    services = (
        db.query(Service)
        .filter(
            Service.docker_source_id == source.id,
            Service.is_docker_container.is_(True),
            Service.docker_container_id.is_not(None),
        )
        .all()
    )
    networks = (
        db.query(Network)
        .filter(
            Network.docker_source_id == source.id,
            Network.is_docker_network.is_(True),
            Network.docker_network_id.is_not(None),
        )
        .all()
    )
    plan = plan_reconciliation(
        [
            ExistingContainer(
                id=service.id,
                native_id=str(service.docker_container_id),
                workload_key=service.docker_workload_key,
                status=service.status,
            )
            for service in services
        ],
        [
            ExistingNetwork(id=network.id, native_id=str(network.docker_network_id))
            for network in networks
        ],
        enumeration,
    )
    by_service_id = {service.id: service for service in services}
    by_network_id = {network.id: network for network in networks}
    for service_id, observation in plan.update_containers:
        _apply_container(
            by_service_id[service_id],
            observation,
            source,
            enumeration.completed_at,
            db,
        )
    for observation in plan.create_containers:
        service = Service(
            name=observation.name,
            slug=_unique_slug(db, observation.name, observation.native_id),
        )
        _apply_container(service, observation, source, enumeration.completed_at, db)
        db.add(service)
    for service_id in plan.stop_container_ids:
        service = by_service_id[service_id]
        if service.status != "stopped":
            service.status = "stopped"
            service.updated_at = enumeration.completed_at
    for network_id, network_observation in plan.update_networks:
        network = by_network_id[network_id]
        network.name = network_observation.name
        network.docker_driver = network_observation.driver
        network.cidr = network_observation.subnet
        network.gateway = network_observation.gateway
        network.updated_at = enumeration.completed_at
    for network_observation in plan.create_networks:
        db.add(
            Network(
                name=network_observation.name,
                docker_network_id=network_observation.native_id,
                docker_driver=network_observation.driver,
                docker_source_id=source.id,
                is_docker_network=True,
                cidr=network_observation.subnet,
                gateway=network_observation.gateway,
                description=(f"Docker {network_observation.driver or ''} network".strip()),
            )
        )

    result = DockerReconciliationResult(
        containers_created=len(plan.create_containers),
        containers_updated=len(plan.update_containers),
        containers_stopped=len(plan.stop_container_ids),
        networks_created=len(plan.create_networks),
        networks_updated=len(plan.update_networks),
        conflicts=plan.conflicts,
    )
    run.containers_created = result.containers_created
    run.containers_updated = result.containers_updated
    run.containers_stopped = result.containers_stopped
    run.networks_created = result.networks_created
    run.networks_updated = result.networks_updated
    run.conflict_count = len(result.conflicts)
    run.status = "succeeded" if enumeration.outcome == "success" else "partial"
    run.completed_at = enumeration.completed_at
    run.lease_token = None
    run.lease_expires_at = None
    if enumeration.outcome == "success":
        source.last_success_at = enumeration.completed_at
    source.updated_at = datetime.now(UTC)
    db.flush()
    return result
