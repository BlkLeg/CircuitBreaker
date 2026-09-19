"""Manual and scheduled Docker orchestration share durable source admission."""

from datetime import UTC, datetime

from app.db.models import DockerSyncRun
from app.schemas.docker import DockerEnumeration


class _KeepOpenSession:
    def __init__(self, session) -> None:
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_args):
        return False


def test_proxy_sync_does_not_require_local_socket(monkeypatch, db_session, app_cfg) -> None:
    from app.services import docker_discovery

    monkeypatch.setenv("CB_DOCKER_HOST", "tcp://docker-proxy:2375")
    monkeypatch.setattr(
        docker_discovery,
        "SessionLocal",
        lambda: _KeepOpenSession(db_session),
    )
    monkeypatch.setattr(docker_discovery, "_emit_run_result", lambda _run_id: None)
    captured = []

    def enumerate_proxy(config):
        captured.append(config)
        now = datetime.now(UTC)
        return DockerEnumeration(
            source_identity=config.identity,
            outcome="success",
            containers_complete=True,
            networks_complete=True,
            attempted_at=now,
            completed_at=now,
        )

    monkeypatch.setattr(docker_discovery, "enumerate_docker", enumerate_proxy)
    run = docker_discovery.queue_configured_sync(db_session, "operator")
    source_id, run_id = run.source_id, run.id
    db_session.commit()

    docker_discovery.run_source_sync(source_id, run_id)

    assert captured[0].base_url == "tcp://docker-proxy:2375"
    completed = db_session.get(DockerSyncRun, run_id)
    assert completed is not None
    assert completed.status == "succeeded"
