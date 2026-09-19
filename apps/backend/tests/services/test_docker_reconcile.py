"""Docker reconciliation is complete-scope-aware and source isolated."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import DockerSource, DockerSyncRun, Network, Service
from app.schemas.docker import (
    DockerContainerObservation,
    DockerEnumeration,
    DockerNetworkObservation,
)
from app.services.docker_reconcile import StaleDockerRun, apply_reconciliation


def _source(db_session, identity: str) -> DockerSource:
    source = DockerSource(
        identity=identity,
        name=identity,
        connection_kind="socket",
        endpoint_hint="local Docker socket",
        enabled=True,
        revision=1,
        parent_provenance="unresolved",
    )
    db_session.add(source)
    db_session.flush()
    return source


def _run(db_session, source: DockerSource, run_id: str) -> DockerSyncRun:
    now = datetime.now(UTC)
    run = DockerSyncRun(
        id=run_id,
        source_id=source.id,
        source_revision=source.revision,
        status="running",
        lease_token="lease",
        started_at=now,
        created_at=now,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _enumeration(
    identity: str,
    containers: list[DockerContainerObservation],
    *,
    complete: bool = True,
    networks: list[DockerNetworkObservation] | None = None,
    outcome: str | None = None,
) -> DockerEnumeration:
    now = datetime.now(UTC)
    return DockerEnumeration(
        source_identity=identity,
        outcome=outcome or ("success" if complete else "partial"),
        containers_complete=complete,
        networks_complete=True,
        attempted_at=now,
        completed_at=now,
        containers=containers,
        networks=networks or [],
    )


def _service(db_session, source: DockerSource, native_id: str, name: str) -> Service:
    service = Service(
        name=name,
        slug=f"{source.identity}-{native_id}",
        docker_source_id=source.id,
        docker_container_id=native_id,
        docker_network_ids=[],
        is_docker_container=True,
        docker_parent_provenance="unresolved",
        status="running",
    )
    db_session.add(service)
    db_session.flush()
    return service


def test_complete_empty_stops_last_container_for_only_its_source(db_session) -> None:
    source_a = _source(db_session, "a")
    source_b = _source(db_session, "b")
    stale = _service(db_session, source_a, "same-native", "web")
    unrelated = _service(db_session, source_b, "same-native", "web")
    run = _run(db_session, source_a, "run-empty")

    result = apply_reconciliation(db_session, source_a.id, run.id, "lease", _enumeration("a", []))
    db_session.commit()

    assert result.containers_stopped == 1
    assert stale.status == "stopped"
    assert unrelated.status == "running"


def test_partial_container_scope_never_marks_absence(db_session) -> None:
    source = _source(db_session, "partial")
    existing = _service(db_session, source, "old", "api")
    run = _run(db_session, source, "run-partial")

    apply_reconciliation(
        db_session,
        source.id,
        run.id,
        "lease",
        _enumeration("partial", [], complete=False),
    )
    db_session.commit()

    assert existing.status == "running"


def test_recreation_uses_complete_compose_identity_not_display_name(db_session) -> None:
    source = _source(db_session, "compose")
    existing = _service(db_session, source, "old-id", "web")
    existing.docker_workload_key = "compose:site:web:1"
    run = _run(db_session, source, "run-recreate")
    observed = DockerContainerObservation(
        native_id="new-id",
        name="web",
        status="running",
        workload_key="compose:site:web:1",
    )

    result = apply_reconciliation(
        db_session,
        source.id,
        run.id,
        "lease",
        _enumeration("compose", [observed]),
    )
    db_session.commit()

    assert result.containers_created == 0
    assert existing.docker_container_id == "new-id"
    assert db_session.query(Service).filter(Service.docker_source_id == source.id).count() == 1


def test_manual_parent_on_container_survives_rediscovery(db_session, factories) -> None:
    source = _source(db_session, "manual-parent")
    source_parent = factories.hardware(name="source-parent")
    manual_parent = factories.hardware(name="manual-parent")
    source.parent_type = "hardware"
    source.parent_id = source_parent.id
    existing = _service(db_session, source, "container", "api")
    existing.hardware_id = manual_parent.id
    existing.docker_parent_provenance = "manual"
    run = _run(db_session, source, "run-manual")

    apply_reconciliation(
        db_session,
        source.id,
        run.id,
        "lease",
        _enumeration(
            "manual-parent",
            [DockerContainerObservation(native_id="container", name="api")],
        ),
    )
    db_session.commit()

    assert existing.hardware_id == manual_parent.id
    assert existing.docker_parent_provenance == "manual"


def test_failed_enumeration_preserves_inventory_and_last_success(db_session) -> None:
    source = _source(db_session, "failure")
    prior_success = datetime(2026, 9, 1, tzinfo=UTC)
    source.last_success_at = prior_success
    existing = _service(db_session, source, "container", "api")
    run = _run(db_session, source, "run-failed")
    failed = _enumeration("failure", [], complete=False, outcome="failed")
    failed.networks_complete = False

    result = apply_reconciliation(db_session, source.id, run.id, "lease", failed)
    db_session.commit()

    assert result.containers_stopped == 0
    assert existing.status == "running"
    assert source.last_success_at == prior_success
    assert run.status == "failed"


def test_same_native_network_id_is_isolated_by_source(db_session) -> None:
    source_a = _source(db_session, "network-a")
    source_b = _source(db_session, "network-b")
    run_a = _run(db_session, source_a, "run-network-a")
    run_b = _run(db_session, source_b, "run-network-b")
    observation = DockerNetworkObservation(
        native_id="same-network-id", name="frontend", driver="bridge"
    )

    apply_reconciliation(
        db_session,
        source_a.id,
        run_a.id,
        "lease",
        _enumeration("network-a", [], networks=[observation]),
    )
    apply_reconciliation(
        db_session,
        source_b.id,
        run_b.id,
        "lease",
        _enumeration("network-b", [], networks=[observation]),
    )
    db_session.commit()

    rows = db_session.query(Network).filter(Network.docker_network_id == "same-network-id").all()
    assert {row.docker_source_id for row in rows} == {source_a.id, source_b.id}


def test_older_run_cannot_apply_after_a_newer_attempt_exists(db_session) -> None:
    source = _source(db_session, "ordered")
    old = _run(db_session, source, "old-run")
    newer = _run(db_session, source, "new-run")
    newer.created_at = old.created_at + timedelta(microseconds=1)
    db_session.flush()

    with pytest.raises(StaleDockerRun):
        apply_reconciliation(
            db_session,
            source.id,
            old.id,
            "lease",
            _enumeration("ordered", []),
        )


def test_ambiguous_recreation_is_reported_without_stopping_candidates(db_session) -> None:
    source = _source(db_session, "ambiguous")
    first = _service(db_session, source, "old-a", "worker-a")
    second = _service(db_session, source, "old-b", "worker-b")
    first.docker_workload_key = "compose:site:worker:1"
    second.docker_workload_key = "compose:site:worker:1"
    run = _run(db_session, source, "run-ambiguous")

    result = apply_reconciliation(
        db_session,
        source.id,
        run.id,
        "lease",
        _enumeration(
            "ambiguous",
            [
                DockerContainerObservation(
                    native_id="new-id",
                    name="worker",
                    workload_key="compose:site:worker:1",
                )
            ],
        ),
    )
    db_session.commit()

    assert result.conflicts == ["ambiguous_workload:compose:site:worker:1"]
    assert result.containers_stopped == 0
    assert first.status == "running"
    assert second.status == "running"
