"""SRV-03 health probes, exercised against a real PostgreSQL.

This file used to assert a contract that no longer exists — a top-level
``status: "ok"`` key and a 503 with ``status: "warming_up"`` — neither of which
any handler in app/main.py has produced since liveness, startup and readiness
were split into /livez, /startupz and /readyz. Nothing collected it, so the rot
was invisible. It now asserts the shape those four handlers actually return.

Where this differs from apps/backend/tests/test_health_endpoints.py: that suite
pins the Redis probe and runs against the testcontainer, and never exercises a
*database* failure. The case below — the discovery contract column disappearing
underneath a running server (migration drift) — is the one that has actually
bitten this project, and the assertion that matters is that it makes /readyz
say "stop routing to me" while /livez keeps saying "do not restart me".
"""

import pytest

from app.core.server_state import ServerState, get_state, set_state


@pytest.fixture(autouse=True)
def _ready_state():
    """The lifecycle state is a module-level singleton. Pin it to READY so the
    readiness assertions below are about dependencies rather than about which
    test happened to run first, and restore whatever was there on the way in.
    """
    previous = get_state()
    set_state(ServerState.READY)
    yield
    set_state(previous)


@pytest.fixture
def redis_up(monkeypatch):
    """Pin the Redis probe to healthy.

    Readiness is the AND of every dependency, so without this the assertions
    about the database would pass for the wrong reason on any machine that has
    no Redis — which includes the default developer setup and CI.
    """
    import app.core.redis as redis_module

    async def _probe() -> bool:
        return True

    monkeypatch.setattr(redis_module, "redis_health", _probe)


class _DriftedEngine:
    """An engine whose schema is missing scan_jobs.error_reason.

    Mirrors the readiness contract check in app.main._probe_dependencies:
    ``SELECT 1`` succeeds, the discovery contract column does not.
    """

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            if "error_reason" in str(stmt):
                raise Exception("column scan_jobs.error_reason does not exist")
            return None

    def connect(self):
        return self._Conn()


def test_legacy_health_keeps_its_shape(client):
    """deploy/setup.sh's install-time wait, scripts/test-mono-e2e.sh and the
    frontend connectivity poll all read this body, so the keys are load-bearing.
    """
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"state", "ready", "uptime_s", "checks"}
    assert body["state"] == "ready"
    assert body["ready"] is True
    assert set(body["checks"]) == {"db", "redis"}
    assert body["checks"]["db"] == "ok"
    assert isinstance(body["uptime_s"], int)


def test_health_does_not_disclose_build_details_to_anonymous_callers(client):
    """Version and extension inventory are fingerprinting material: they tell a
    scanner which published CVEs to try before it has any credentials."""
    for path in ("/api/v1/health", "/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz"):
        body = client.get(path).json()
        assert "version" not in body, f"{path} disclosed the build version"
        assert "timescaledb_available" not in body, f"{path} disclosed the extension inventory"


def test_health_discloses_build_detail_to_an_authenticated_caller(client, auth_headers):
    """The anonymous body withholds it; an authenticated operator still needs
    the build version and extension inventory to diagnose a deployment."""
    from app.core.config import settings

    resp = client.get("/api/v1/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == settings.app_version
    assert "timescaledb_available" in body


def test_livez_touches_no_dependency(client):
    resp = client.get("/api/v1/livez")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"
    assert isinstance(body["uptime_s"], int)


def test_startupz_reports_initialisation_complete(client):
    resp = client.get("/api/v1/startupz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["started"] is True


def test_startupz_is_503_until_initialisation_finishes(client):
    set_state(ServerState.STARTING)
    resp = client.get("/api/v1/startupz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["state"] == "starting"
    assert body["started"] is False


def test_readyz_is_200_against_a_real_database(client, redis_up):
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["state"] == "ready"
    assert body["checks"] == {"db": "ok", "redis": "ok"}


def test_readyz_is_503_while_stopping(client, redis_up):
    """SIGTERM drain: stop taking new traffic before the process goes away."""
    set_state(ServerState.STOPPING)
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["state"] == "stopping"


def test_schema_drift_makes_readyz_unready_without_making_the_process_dead(client, redis_up):
    """Migration drift is a routing decision, not a restart decision.

    /readyz must report the database as broken so the load balancer stops
    sending traffic, while /livez stays 200 — restarting the process cannot
    conjure a missing column, it only turns an outage into a crash loop. Legacy
    /health keeps answering 200 with the failure in `checks` because the Docker
    HEALTHCHECK and deploy scripts still read it.
    """
    import app.main as main_mod

    original_engine = main_mod.engine
    main_mod.engine = _DriftedEngine()
    try:
        ready = client.get("/api/v1/readyz")
        assert ready.status_code == 503
        ready_body = ready.json()
        assert ready_body["ready"] is False
        assert ready_body["checks"]["db"] == "error"
        assert ready_body["checks"]["redis"] == "ok"

        assert client.get("/api/v1/livez").status_code == 200

        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["checks"]["db"] == "error"
    finally:
        main_mod.engine = original_engine
