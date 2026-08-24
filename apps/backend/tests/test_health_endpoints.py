"""SRV-03: liveness, startup, readiness and dependency health must be distinct.

One conflated endpoint cannot express the difference between "restart me" and
"do not send me traffic yet", which are the two actions an orchestrator has.

These run against the async ASGI `client` fixture (tests/conftest.py) — the
project's pytest config sets ``asyncio_mode = "auto"``, so plain `async def`
tests are collected without a marker.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.server_state import ServerState, get_state, set_state


@pytest.fixture(autouse=True)
def _ready_state():
    """The lifecycle state is a module-level singleton, so a test that leaves it
    on STARTING/STOPPING would poison every later test in the session.

    Teardown restores whatever the state was on the way in rather than pinning
    it to READY: `ws_client` (tests/conftest.py) runs the app's real lifespan
    and does leave a different state behind, and this file must not silently
    rewrite that for the tests that follow it.
    """
    previous = get_state()
    set_state(ServerState.READY)
    yield
    set_state(previous)


async def test_livez_is_200_whenever_the_process_is_running(client: AsyncClient):
    """Liveness must not consult dependencies: a Redis outage is not a reason
    to have the orchestrator kill an otherwise healthy process."""
    response = await client.get("/api/v1/livez")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert isinstance(body["uptime_s"], int)


async def test_livez_stays_200_while_starting(client: AsyncClient):
    set_state(ServerState.STARTING)
    response = await client.get("/api/v1/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_startupz_is_503_until_startup_completes(client: AsyncClient):
    set_state(ServerState.STARTING)
    response = await client.get("/api/v1/startupz")
    assert response.status_code == 503
    body = response.json()
    assert body["state"] == "starting"
    assert body["started"] is False


async def test_startupz_is_200_once_ready(client: AsyncClient):
    response = await client.get("/api/v1/startupz")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["started"] is True


async def test_startupz_is_200_while_stopping(client: AsyncClient):
    """Startup is a latch, not a mirror of readiness: once initialisation has
    finished, draining must not make an orchestrator think it never started."""
    set_state(ServerState.STOPPING)
    response = await client.get("/api/v1/startupz")
    assert response.status_code == 200
    assert response.json()["started"] is True


async def test_readyz_reports_dependency_checks(client: AsyncClient):
    response = await client.get("/api/v1/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert set(body["checks"]) == {"db", "redis"}
    assert body["ready"] is (response.status_code == 200)
    assert body["state"] == "ready"


async def test_readyz_is_503_while_stopping(client: AsyncClient):
    """SIGTERM drain: stop taking new traffic before the process goes away."""
    set_state(ServerState.STOPPING)
    response = await client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["state"] == "stopping"


def _patch_redis(monkeypatch, up: bool) -> None:
    """Pin the Redis probe. The dev host this suite runs on has no Redis, so
    without pinning, the "dependency is up" branch would never be exercised and
    the "dependency is down" assertions would pass vacuously."""
    import app.core.redis as redis_module

    async def _probe() -> bool:
        return up

    monkeypatch.setattr(redis_module, "redis_health", _probe)


async def test_readyz_is_200_when_every_dependency_answers(client: AsyncClient, monkeypatch):
    _patch_redis(monkeypatch, up=True)

    response = await client.get("/api/v1/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["checks"] == {"db": "ok", "redis": "ok"}


async def test_readyz_is_503_when_a_dependency_is_down(client: AsyncClient, monkeypatch):
    """A down dependency is a routing decision, so it shows up here — and only
    here. /livez stays 200 through the same outage."""
    _patch_redis(monkeypatch, up=False)

    response = await client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["redis"] == "error"

    assert (await client.get("/api/v1/livez")).status_code == 200


async def test_legacy_health_keeps_its_shape(client: AsyncClient):
    """The frontend's connectivity poll, scripts/test-mono-e2e.sh and
    deploy/setup.sh's install-time wait all read this body."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"state", "ready", "uptime_s", "checks"}
    assert set(body["checks"]) == {"db", "redis"}
    assert body["state"] == "ready"
    assert body["ready"] is True


async def test_health_endpoints_do_not_leak_version_to_anonymous_callers(client: AsyncClient):
    for path in ("/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz", "/api/v1/health"):
        body = (await client.get(path)).json()
        assert "version" not in body, f"{path} disclosed build version to an anonymous caller"
        assert "timescaledb_available" not in body, f"{path} disclosed extension inventory"


@pytest.mark.parametrize("path", ["/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz"])
async def test_head_is_supported(client: AsyncClient, path: str):
    response = await client.head(path)
    assert response.status_code in (200, 503)
