"""Configured Docker source identity, durable run admission, and parent policy."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    ComputeUnit,
    DockerSource,
    DockerSyncRun,
    Hardware,
    Network,
    Service,
)
from app.schemas.docker import (
    DockerConnectionConfig,
    DockerManagedContainerOut,
    DockerParentAssignment,
    DockerSourceOut,
    DockerSyncRunOut,
)

_DEFAULT_SOCKET = "/var/run/docker.sock"
_RUN_LEASE = timedelta(minutes=2)
_ALLOWED_PROXY_SCHEMES = {"tcp", "http", "https"}


class DockerSourceConflict(RuntimeError):
    """A source revision or active run prevents the requested mutation."""


class DockerSourceConfigurationError(ValueError):
    """The effective server-side Docker endpoint is not allowed."""


def _network_types(settings: Any) -> list[str]:
    raw = getattr(settings, "docker_network_types", None)
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                selected = [str(value) for value in parsed if str(value)]
                if selected:
                    return selected
        except ValueError:
            return ["bridge"]
    return ["bridge"]


def resolve_source_config(
    settings: Any,
    environment: Mapping[str, str] | None = None,
) -> DockerConnectionConfig:
    """Resolve only the installed socket or explicitly configured proxy."""
    env = environment if environment is not None else os.environ
    configured_host = env.get("CB_DOCKER_HOST", "").strip()
    if configured_host:
        parsed = urlparse(configured_host)
        if (
            parsed.scheme not in _ALLOWED_PROXY_SCHEMES
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise DockerSourceConfigurationError(
                "CB_DOCKER_HOST must name an approved HTTP(S)/TCP Docker proxy."
            )
        base_url = configured_host
        port = f":{parsed.port}" if parsed.port else ""
        endpoint_hint = f"{parsed.scheme}://{parsed.hostname}{port}"
        connection_kind: Literal["socket", "proxy"] = "proxy"
    else:
        socket_path = str(getattr(settings, "docker_socket_path", None) or _DEFAULT_SOCKET).strip()
        if not socket_path.startswith("/") or "\x00" in socket_path:
            raise DockerSourceConfigurationError(
                "The configured Docker socket path must be absolute."
            )
        base_url = f"unix://{socket_path}"
        endpoint_hint = "local Docker socket"
        connection_kind = "socket"
    identity = hashlib.sha256(base_url.encode()).hexdigest()
    return DockerConnectionConfig(
        identity=identity,
        base_url=base_url,
        endpoint_hint=endpoint_hint,
        connection_kind=connection_kind,
        network_types=_network_types(settings),
    )


def get_or_create_configured_source(db: Session, config: DockerConnectionConfig) -> DockerSource:
    """Return the row for the one currently configured daemon; caller commits."""
    source = db.query(DockerSource).filter(DockerSource.identity == config.identity).first()
    if source is None:
        db.execute(
            pg_insert(DockerSource)
            .values(
                identity=config.identity,
                name="Docker host",
                connection_kind=config.connection_kind,
                endpoint_hint=config.endpoint_hint,
                enabled=True,
                revision=1,
                parent_provenance="unresolved",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["identity"])
        )
        source = db.query(DockerSource).filter(DockerSource.identity == config.identity).one()
    else:
        source.connection_kind = config.connection_kind
        source.endpoint_hint = config.endpoint_hint
        if not source.enabled:
            source.enabled = True
            source.revision += 1
    for other in (
        db.query(DockerSource)
        .filter(
            DockerSource.id != source.id,
            DockerSource.enabled.is_(True),
        )
        .all()
    ):
        other.enabled = False
        other.revision += 1
        other.updated_at = datetime.now(UTC)
    return source


def _interrupt_expired_runs(db: Session, source_id: int, now: datetime) -> None:
    expired = (
        db.query(DockerSyncRun)
        .filter(
            DockerSyncRun.source_id == source_id,
            DockerSyncRun.status.in_(("queued", "running")),
            DockerSyncRun.lease_expires_at.is_not(None),
            DockerSyncRun.lease_expires_at <= now,
        )
        .with_for_update()
        .all()
    )
    for run in expired:
        run.status = "interrupted"
        run.completed_at = now
        run.reason_code = "lease_expired"
        run.safe_message = "The Docker sync worker stopped before completing the run."
        run.lease_token = None
        run.lease_expires_at = None


def start_sync(
    db: Session,
    source_id: int,
    actor: str,
    *,
    now: datetime | None = None,
) -> DockerSyncRun:
    """Durably admit one run, rejecting a source that already has active work."""
    current = now or datetime.now(UTC)
    source = db.query(DockerSource).filter(DockerSource.id == source_id).with_for_update().first()
    if source is None or not source.enabled:
        raise DockerSourceConfigurationError("Docker source is unavailable.")
    _interrupt_expired_runs(db, source.id, current)
    active = (
        db.query(DockerSyncRun)
        .filter(
            DockerSyncRun.source_id == source.id,
            DockerSyncRun.status.in_(("queued", "running")),
        )
        .first()
    )
    if active is not None:
        raise DockerSourceConflict(f"Docker source already has active run {active.id}.")
    run = DockerSyncRun(
        id=uuid4().hex,
        source_id=source.id,
        source_revision=source.revision,
        status="queued",
        triggered_by=actor[:200],
        lease_expires_at=current + _RUN_LEASE,
        created_at=current,
        updated_at=current,
    )
    db.add(run)
    db.flush()
    return run


def assign_source_parent(
    db: Session,
    source_id: int,
    assignment: DockerParentAssignment,
    actor: str,
) -> DockerSource:
    """Apply a revision-checked manual parent without overwriting manual children."""
    source = db.query(DockerSource).filter(DockerSource.id == source_id).with_for_update().first()
    if source is None:
        raise DockerSourceConfigurationError("Docker source is unavailable.")
    if source.revision != assignment.expected_revision:
        raise DockerSourceConflict("Docker source changed; refresh and try again.")
    if assignment.parent_type == "hardware":
        if db.get(Hardware, assignment.parent_id) is None:
            raise DockerSourceConfigurationError("Selected hardware parent does not exist.")
    elif assignment.parent_type == "compute":
        if db.get(ComputeUnit, assignment.parent_id) is None:
            raise DockerSourceConfigurationError("Selected compute parent does not exist.")

    source.parent_type = assignment.parent_type
    source.parent_id = assignment.parent_id
    source.parent_provenance = "manual" if assignment.parent_id else "unresolved"
    source.parent_assigned_by = actor[:200]
    source.revision += 1
    source.updated_at = datetime.now(UTC)

    children = (
        db.query(Service)
        .filter(
            Service.docker_source_id == source.id,
            Service.docker_parent_provenance.in_(("unresolved", "automatic")),
        )
        .all()
    )
    for service in children:
        service.compute_id = assignment.parent_id if assignment.parent_type == "compute" else None
        if assignment.parent_type == "hardware":
            service.hardware_id = assignment.parent_id
        elif assignment.parent_type == "compute" and assignment.parent_id is not None:
            compute = db.get(ComputeUnit, assignment.parent_id)
            service.hardware_id = compute.hardware_id if compute else None
        else:
            service.hardware_id = None
        service.docker_parent_provenance = "automatic" if assignment.parent_id else "unresolved"
    db.flush()
    return source


def clear_deleted_parent(db: Session, source: DockerSource) -> bool:
    """Turn a deleted polymorphic parent into an explicit unresolved state."""
    if source.parent_type == "hardware":
        exists = db.get(Hardware, source.parent_id) is not None
    elif source.parent_type == "compute":
        exists = db.get(ComputeUnit, source.parent_id) is not None
    else:
        exists = True
    if exists:
        return False
    source.parent_type = None
    source.parent_id = None
    source.parent_provenance = "unresolved"
    source.parent_assigned_by = None
    source.updated_at = datetime.now(UTC)
    return True


def latest_run(db: Session, source_id: int) -> DockerSyncRun | None:
    _interrupt_expired_runs(db, source_id, datetime.now(UTC))
    return (
        db.query(DockerSyncRun)
        .filter(DockerSyncRun.source_id == source_id)
        .order_by(DockerSyncRun.created_at.desc())
        .first()
    )


def configured_status(db: Session) -> dict[str, Any]:
    """Return the configured source status while owning its transaction boundary."""
    from app.services.settings_service import get_or_create_settings

    try:
        config = resolve_source_config(get_or_create_settings(db))
        source = get_or_create_configured_source(db, config)
        clear_deleted_parent(db, source)
        run = latest_run(db, source.id)
        containers = (
            db.query(Service)
            .filter(
                Service.docker_source_id == source.id,
                Service.is_docker_container.is_(True),
            )
            .count()
        )
        networks = (
            db.query(Network)
            .filter(
                Network.docker_source_id == source.id,
                Network.is_docker_network.is_(True),
            )
            .count()
        )
        db.commit()
        db.refresh(source)
        if run is not None:
            db.refresh(run)
    except Exception:
        db.rollback()
        raise
    return {
        "available": bool(run and run.status in {"succeeded", "partial"}),
        "container_count": containers,
        "network_count": networks,
        "endpoint_hint": source.endpoint_hint,
        "source": DockerSourceOut.model_validate(source),
        "last_sync": DockerSyncRunOut.model_validate(run) if run else None,
        "error": run.safe_message if run and run.status in {"failed", "partial"} else None,
    }


def list_configured_sources(db: Session) -> list[DockerSource]:
    """Ensure the configured source exists and return all durable source records."""
    from app.services.settings_service import get_or_create_settings

    try:
        config = resolve_source_config(get_or_create_settings(db))
        get_or_create_configured_source(db, config)
        sources = db.query(DockerSource).order_by(DockerSource.created_at.asc()).all()
        for source in sources:
            clear_deleted_parent(db, source)
        db.commit()
        for source in sources:
            db.refresh(source)
        return sources
    except Exception:
        db.rollback()
        raise


def list_source_containers(db: Session, source_id: int) -> list[DockerManagedContainerOut]:
    """Project one source's managed containers without leaking session work to API."""
    if db.get(DockerSource, source_id) is None:
        raise DockerSourceConfigurationError("Docker source not found.")
    services = (
        db.query(Service)
        .filter(
            Service.docker_source_id == source_id,
            Service.is_docker_container.is_(True),
            Service.docker_container_id.is_not(None),
        )
        .order_by(Service.name.asc(), Service.id.asc())
        .all()
    )
    return [
        DockerManagedContainerOut(
            id=service.id,
            source_id=source_id,
            native_id=str(service.docker_container_id or ""),
            name=service.name,
            image=service.docker_image,
            status=service.status,
            ip_address=service.ip_address,
            workload_key=service.docker_workload_key,
            network_ids=[str(value) for value in (service.docker_network_ids or [])],
            parent_type=(
                "compute"
                if service.compute_id is not None
                else "hardware"
                if service.hardware_id is not None
                else None
            ),
            parent_id=service.compute_id or service.hardware_id,
            parent_provenance=service.docker_parent_provenance,
            last_seen_at=service.docker_last_seen_at,
        )
        for service in services
    ]


def get_sync_run(db: Session, run_id: str) -> DockerSyncRun:
    """Return a run after repairing any expired lease for its source."""
    try:
        run = db.get(DockerSyncRun, run_id)
        if run is None:
            raise DockerSourceConfigurationError("Docker sync run not found.")
        latest_run(db, run.source_id)
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise


def assign_source_parent_committed(
    db: Session,
    source_id: int,
    assignment: DockerParentAssignment,
    actor: str,
) -> DockerSource:
    """Apply a source parent assignment atomically for API callers."""
    try:
        source = assign_source_parent(db, source_id, assignment, actor)
        db.commit()
        db.refresh(source)
        return source
    except Exception:
        db.rollback()
        raise
