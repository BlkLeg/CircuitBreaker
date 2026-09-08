"""Configured Docker source resolution, leases, and parent revisions."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.db.models import DockerSource, Hardware, Service
from app.schemas.docker import DockerParentAssignment
from app.schemas.services import ServiceUpdate
from app.services import services_service
from app.services.docker_sources import (
    DockerSourceConfigurationError,
    DockerSourceConflict,
    assign_source_parent,
    clear_deleted_parent,
    get_or_create_configured_source,
    resolve_source_config,
    start_sync,
)


def test_explicit_proxy_is_used_without_a_local_socket() -> None:
    config = resolve_source_config(
        SimpleNamespace(docker_socket_path="/missing/docker.sock"),
        {"CB_DOCKER_HOST": "tcp://docker-proxy:2375"},
    )

    assert config.connection_kind == "proxy"
    assert config.base_url == "tcp://docker-proxy:2375"
    assert config.endpoint_hint == "tcp://docker-proxy:2375"


@pytest.mark.parametrize(
    "endpoint",
    [
        "ssh://host/run/docker.sock",
        "tcp://user:password@docker-proxy:2375",
        "http://docker-proxy:2375/?token=secret",
        "not-a-url",
    ],
)
def test_unapproved_proxy_shapes_are_rejected(endpoint: str) -> None:
    with pytest.raises(DockerSourceConfigurationError):
        resolve_source_config(SimpleNamespace(), {"CB_DOCKER_HOST": endpoint})


def test_active_run_conflicts_and_expired_run_is_interrupted(db_session) -> None:
    config = resolve_source_config(SimpleNamespace(), {})
    source = get_or_create_configured_source(db_session, config)
    now = datetime.now(UTC)
    first = start_sync(db_session, source.id, "operator", now=now)
    db_session.commit()

    with pytest.raises(DockerSourceConflict):
        start_sync(db_session, source.id, "operator", now=now)

    first.lease_expires_at = now - timedelta(seconds=1)
    db_session.commit()
    second = start_sync(db_session, source.id, "scheduler", now=now)
    db_session.commit()

    db_session.refresh(first)
    assert first.status == "interrupted"
    assert second.status == "queued"


def test_parent_assignment_is_revision_checked(db_session) -> None:
    source = DockerSource(
        identity="parent-source",
        name="Docker",
        connection_kind="socket",
        endpoint_hint="local Docker socket",
        revision=1,
        enabled=True,
        parent_provenance="unresolved",
    )
    parent = Hardware(name="docker-host")
    db_session.add_all([source, parent])
    db_session.commit()

    assigned = assign_source_parent(
        db_session,
        source.id,
        DockerParentAssignment(parent_type="hardware", parent_id=parent.id, expected_revision=1),
        "operator",
    )
    db_session.commit()

    assert assigned.parent_id == parent.id
    assert assigned.parent_provenance == "manual"
    assert assigned.revision == 2
    with pytest.raises(DockerSourceConflict):
        assign_source_parent(
            db_session,
            source.id,
            DockerParentAssignment(parent_type=None, parent_id=None, expected_revision=1),
            "operator",
        )


def test_deleted_parent_becomes_unresolved(db_session) -> None:
    source = DockerSource(
        identity="deleted-parent",
        name="Docker",
        connection_kind="socket",
        endpoint_hint="local Docker socket",
        revision=1,
        enabled=True,
        parent_type="hardware",
        parent_id=991_991,
        parent_provenance="manual",
    )
    db_session.add(source)
    db_session.flush()

    assert clear_deleted_parent(db_session, source) is True
    assert source.parent_type is None
    assert source.parent_id is None
    assert source.parent_provenance == "unresolved"


def test_direct_container_parent_edit_becomes_manual(db_session) -> None:
    parent = Hardware(name="manual-host")
    service = Service(
        name="api",
        slug="manual-docker-service",
        docker_container_id="manual-container",
        docker_network_ids=[],
        docker_parent_provenance="automatic",
        is_docker_container=True,
    )
    db_session.add_all([parent, service])
    db_session.commit()

    services_service.update_service(db_session, service.id, ServiceUpdate(hardware_id=parent.id))

    assert service.hardware_id == parent.id
    assert service.docker_parent_provenance == "manual"
