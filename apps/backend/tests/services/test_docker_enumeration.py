"""Structured Docker enumeration distinguishes coverage from empty data."""

from contextlib import contextmanager
from types import SimpleNamespace

from app.schemas.docker import DockerConnectionConfig
from app.services import docker_enumeration


def _config() -> DockerConnectionConfig:
    return DockerConnectionConfig(
        identity="source-a",
        base_url="unix:///var/run/docker.sock",
        endpoint_hint="local Docker socket",
        connection_kind="socket",
        network_types=["bridge"],
    )


class _ResourceList:
    def __init__(self, values=None, error: Exception | None = None) -> None:
        self.values = values or []
        self.error = error

    def list(self, **_kwargs):
        if self.error:
            raise self.error
        return self.values


class _Client:
    def __init__(self, containers=None, networks=None) -> None:
        self.containers = containers or _ResourceList()
        self.networks = networks or _ResourceList()

    def info(self):
        return {"ID": "daemon-native-id"}


def _install_client(monkeypatch, client: _Client) -> None:
    @contextmanager
    def fake_client(_base_url, **_kwargs):
        yield client

    monkeypatch.setattr(docker_enumeration, "docker_client", fake_client)


def test_successful_empty_enumeration_is_complete(monkeypatch) -> None:
    _install_client(monkeypatch, _Client())

    result = docker_enumeration.enumerate_docker(_config())

    assert result.outcome == "success"
    assert result.containers_complete is True
    assert result.networks_complete is True
    assert result.containers == []


def test_native_network_and_compose_identity_are_preserved(monkeypatch) -> None:
    network = SimpleNamespace(
        id="network-immutable-id",
        name="frontend",
        attrs={
            "Driver": "bridge",
            "Scope": "local",
            "IPAM": {"Config": [{"Subnet": "172.20.0.0/16", "Gateway": "172.20.0.1"}]},
        },
    )
    container = SimpleNamespace(
        id="container-immutable-id",
        short_id="container-im",
        name="web-1",
        status="running",
        image=SimpleNamespace(tags=["web:latest"]),
        attrs={
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "site",
                    "com.docker.compose.service": "web",
                    "com.docker.compose.container-number": "1",
                }
            },
            "NetworkSettings": {
                "Networks": {
                    "frontend": {
                        "NetworkID": "network-immutable-id",
                        "IPAddress": "172.20.0.2",
                    }
                }
            },
        },
    )
    _install_client(
        monkeypatch,
        _Client(_ResourceList([container]), _ResourceList([network])),
    )

    result = docker_enumeration.enumerate_docker(_config())

    assert result.networks[0].native_id == "network-immutable-id"
    assert result.containers[0].network_ids == ["network-immutable-id"]
    assert result.containers[0].workload_key == "compose:site:web:1"


def test_partial_network_failure_preserves_complete_container_scope(monkeypatch) -> None:
    _install_client(
        monkeypatch,
        _Client(networks=_ResourceList(error=RuntimeError("secret provider detail"))),
    )

    result = docker_enumeration.enumerate_docker(_config())

    assert result.outcome == "partial"
    assert result.containers_complete is True
    assert result.networks_complete is False
    assert "secret provider detail" not in (result.safe_message or "")


def test_unreachable_daemon_is_failure_not_empty_success(monkeypatch) -> None:
    @contextmanager
    def unavailable(_base_url, **_kwargs):
        raise RuntimeError("unix:///secret/docker.sock")
        yield

    monkeypatch.setattr(docker_enumeration, "docker_client", unavailable)

    result = docker_enumeration.enumerate_docker(_config())

    assert result.outcome == "failed"
    assert result.containers_complete is False
    assert result.reason_code == "daemon_unreachable"
    assert "/secret/" not in (result.safe_message or "")


def test_daemon_timeout_has_a_distinct_safe_reason(monkeypatch) -> None:
    @contextmanager
    def timed_out(_base_url, **_kwargs):
        raise TimeoutError("tcp://secret-proxy:2375")
        yield

    monkeypatch.setattr(docker_enumeration, "docker_client", timed_out)

    result = docker_enumeration.enumerate_docker(_config())

    assert result.outcome == "failed"
    assert result.reason_code == "daemon_timeout"
    assert "secret-proxy" not in (result.safe_message or "")


def test_container_timeout_is_partial_when_network_scope_completed(monkeypatch) -> None:
    _install_client(
        monkeypatch,
        _Client(containers=_ResourceList(error=TimeoutError("slow container list"))),
    )

    result = docker_enumeration.enumerate_docker(_config())

    assert result.outcome == "partial"
    assert result.containers_complete is False
    assert result.networks_complete is True
    assert result.reason_code == "container_enumeration_timeout"
