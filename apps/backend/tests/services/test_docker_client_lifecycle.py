"""The Docker client must never outlive the call that opened it.

``docker.DockerClient`` owns a ``requests.Session`` whose keep-alive connection is
an AF_UNIX socket for the default ``unix://`` transport, and it is not a context
manager: dropping the reference leaves the socket open until the garbage
collector reaches it, at which point the finaliser reports
``ResourceWarning: unclosed <socket.socket ... family=1 ...>``. Under pytest's
unraisable hook that warning fails whichever test the collector happened to
interrupt, which is how a leak in ``/api/v1/discovery/status`` came back as an
error in ``tests/integration/test_discovery.py``'s *setup*.

Worse, ``DockerClient(...)`` negotiates the API version inside its constructor, so
an unreachable daemon raises with the half-built session already unreachable to
the caller — a ``finally: client.close()`` cannot fix that one. The pre-flight in
``discovery_safe.docker_client`` is what these tests pin: no client is
constructed at all unless something is listening and willing.
"""

from __future__ import annotations

import importlib
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.services import discovery_safe

docker = importlib.import_module("docker")


class _ConstructorReached(AssertionError):
    """Raised by the spy so a missing pre-flight fails loudly rather than leaking."""


@pytest.fixture
def unix_daemon(tmp_path: Path) -> Iterator[socket.socket]:
    """A listening AF_UNIX socket standing in for a reachable Docker daemon.

    It accepts connections and answers nothing, which is all the pre-flight looks
    at: it connects and hangs up without speaking HTTP. The accept loop is not
    decoration — an unattended backlog fills after a handful of probes and Linux
    then fails further connects with EAGAIN, which would make the last test below
    measure the backlog rather than the descriptors.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(tmp_path / "docker.sock"))
    server.listen(8)
    # A blocked accept() does not wake when another thread closes the socket, so
    # the loop polls instead and teardown is immediate rather than a 5s join.
    server.settimeout(0.05)
    stop = threading.Event()

    def _accept_forever() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.close()

    accepting = threading.Thread(target=_accept_forever, daemon=True)
    accepting.start()
    try:
        yield server
    finally:
        stop.set()
        accepting.join(timeout=5)
        server.close()


class _FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_an_unreachable_socket_never_reaches_the_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(**kwargs: Any) -> None:
        raise _ConstructorReached("DockerClient was constructed for a dead endpoint")

    monkeypatch.setattr(docker, "DockerClient", _explode)

    missing = tmp_path / "no-such-docker.sock"
    with pytest.raises(docker.errors.DockerException) as excinfo:  # noqa: PT012
        with discovery_safe.docker_client(f"unix://{missing}"):
            pass

    # DockerException specifically: every call site in the app already handles
    # it, so the pre-flight changes where the failure comes from and nothing else.
    assert "not reachable" in str(excinfo.value)


def test_a_refused_tcp_endpoint_never_reaches_the_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(**kwargs: Any) -> None:
        raise _ConstructorReached("DockerClient was constructed for a dead endpoint")

    monkeypatch.setattr(docker, "DockerClient", _explode)

    # Bind and close, so the port is one nothing is listening on.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    with pytest.raises(docker.errors.DockerException):  # noqa: PT012
        with discovery_safe.docker_client(f"tcp://127.0.0.1:{port}"):
            pass


def test_the_client_is_closed_on_the_way_out(
    unix_daemon: socket.socket, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[_FakeClient] = []

    def _make(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(docker, "DockerClient", _make)

    with discovery_safe.docker_client(f"unix://{unix_daemon.getsockname()}") as client:
        assert client.closed is False

    assert [c.closed for c in created] == [True]


def test_the_client_is_closed_when_the_body_raises(
    unix_daemon: socket.socket, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failing path is the one that used to leak in `_test_docker`, which
    closed the client only after a successful `info()` call."""
    created: list[_FakeClient] = []

    def _make(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(docker, "DockerClient", _make)

    with pytest.raises(RuntimeError):  # noqa: PT012
        with discovery_safe.docker_client(f"unix://{unix_daemon.getsockname()}"):
            raise RuntimeError("daemon said no")

    assert [c.closed for c in created] == [True]


def test_the_probe_leaves_no_socket_of_its_own_behind(unix_daemon: socket.socket) -> None:
    """The pre-flight's own socket is closed too — it would otherwise trade one
    leaked descriptor for another."""
    before = len(list(Path("/proc/self/fd").iterdir()))
    for _ in range(20):
        discovery_safe._probe_docker_endpoint(f"unix://{unix_daemon.getsockname()}", 2.0)
    after = len(list(Path("/proc/self/fd").iterdir()))
    assert after <= before + 1, f"probe leaked descriptors: {before} -> {after}"
