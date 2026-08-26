"""SRV-03: degraded is a health state of its own, and readiness rejects writes.

Two of SRV-03's normative clauses were unmet before this suite existed:

* there was no *degraded* state anywhere in the server — a partial outage was
  reported as "not ready", which tells an operator to take the node out of
  service when the inventory it serves is still perfectly safe to read and
  edit; and
* readiness only *reported*. `/readyz` returned 503 and nothing refused the
  write that arrived anyway.

The matrix below is the dependency fault matrix the requirement's acceptance
asks for: for each combination of dependency verdicts it asserts the health
state, what the probe endpoints tell an orchestrator, and — the part that was
missing — what the server itself then permits.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import health, write_admission
from app.core.health import HealthState
from app.core.server_state import ServerState, get_state, set_state


@pytest.fixture(autouse=True)
def _isolated_health_state():
    """Health is process-global: a cached verdict or an armed gate that leaked
    out of one test would decide the next one's outcome."""
    previous_state = get_state()
    previous_armed = write_admission.is_armed()
    set_state(ServerState.READY)
    health.reset_cache()
    yield
    set_state(previous_state)
    health.reset_cache()
    if previous_armed:
        write_admission.arm()
    else:
        write_admission.disarm()


def _pin_dependencies(monkeypatch, *, db: bool, redis: bool) -> None:
    """Pin both dependency probes. The dev host has no Redis, so without
    pinning the "dependency is up" branches never run."""
    import app.core.redis as redis_module

    monkeypatch.setattr(health, "_probe_db", lambda: "ok" if db else "error")

    async def _redis_probe() -> bool:
        return redis

    monkeypatch.setattr(redis_module, "redis_health", _redis_probe)


# ── The health-state contract ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("db_up", "redis_up", "expected_state", "writes_ok"),
    [
        (True, True, HealthState.READY, True),
        # RC-05: Redis is a disposable coordination layer. Losing it costs
        # optional capability, not the inventory, so the server is degraded and
        # inventory edits stay safe.
        (True, False, HealthState.DEGRADED, True),
        # PostgreSQL is the source of truth: no database is never "degraded".
        (False, True, HealthState.NOT_READY, False),
        (False, False, HealthState.NOT_READY, False),
    ],
)
def test_dependency_matrix_classification(db_up, redis_up, expected_state, writes_ok):
    checks = {"db": "ok" if db_up else "error", "redis": "ok" if redis_up else "error"}
    snapshot = health.classify("ready", checks)
    assert snapshot.state is expected_state
    assert snapshot.writes_permitted is writes_ok


def test_draining_outranks_healthy_dependencies():
    """A process that is going away stops admitting writes even with every
    dependency green — otherwise SIGTERM would accept work it cannot finish."""
    snapshot = health.classify("stopping", {"db": "ok", "redis": "ok"})
    assert snapshot.state is HealthState.STOPPING
    assert snapshot.writes_permitted is False


async def test_readyz_reports_degraded_rather_than_a_bare_not_ready(
    client: AsyncClient, monkeypatch
):
    _pin_dependencies(monkeypatch, db=True, redis=False)

    response = await client.get("/api/v1/readyz")

    body = response.json()
    assert body["health"] == "degraded"
    assert body["degraded"] == ["redis"]
    # Degraded still means "do not send me traffic that needs the missing
    # capability", so the readiness signal itself is unchanged...
    assert response.status_code == 503
    assert body["ready"] is False
    # ...but the inventory is safe to edit, and the server says so.
    assert body["writes_permitted"] is True


async def test_readyz_distinguishes_degraded_from_not_ready(client: AsyncClient, monkeypatch):
    _pin_dependencies(monkeypatch, db=False, redis=True)

    body = (await client.get("/api/v1/readyz")).json()

    assert body["health"] == "not_ready"
    assert body["degraded"] == []
    assert body["writes_permitted"] is False


async def test_legacy_health_carries_the_state_without_changing_its_shape(
    client: AsyncClient, monkeypatch
):
    """The frontend poll and deploy/setup.sh read this body; the new fields are
    additive and every field they already read still means what it did."""
    _pin_dependencies(monkeypatch, db=True, redis=False)

    body = (await client.get("/api/v1/health")).json()

    assert set(body) >= {"state", "ready", "uptime_s", "checks", "health", "degraded"}
    assert body["state"] == "ready"
    assert body["ready"] is True
    assert set(body["checks"]) == {"db", "redis"}
    assert body["health"] == "degraded"


async def test_livez_ignores_every_dependency_verdict(client: AsyncClient, monkeypatch):
    """Liveness decides restarts. A degraded or not-ready process must not be
    killed and replaced by another process that will be just as not-ready."""
    _pin_dependencies(monkeypatch, db=False, redis=False)

    response = await client.get("/api/v1/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


# ── Readiness enforcement ──────────────────────────────────────────────────


async def test_a_write_is_refused_when_the_database_cannot_serve_it(
    client: AsyncClient, monkeypatch
):
    """The clause that was unmet: not "readiness reports", but "readiness
    rejects writes when they cannot be served safely"."""
    _pin_dependencies(monkeypatch, db=False, redis=True)

    response = await client.post("/api/v1/hardware", json={"name": "nas"})

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == write_admission.ERROR_CODE_NOT_READY
    assert body["health"] == "not_ready"
    assert response.headers["Retry-After"]


async def test_a_read_is_still_served_when_writes_are_refused(client: AsyncClient, monkeypatch):
    """RC-05 keeps health and diagnostics safe in every state, and the guard is
    a *write* guard: refusing reads would take away the only view an operator
    has while recovering."""
    _pin_dependencies(monkeypatch, db=False, redis=True)

    assert (await client.get("/api/v1/livez")).status_code == 200
    assert (await client.get("/api/v1/readyz")).status_code == 503
    assert (await client.get("/api/v1/health")).status_code == 200


async def test_a_write_is_admitted_while_degraded(client: AsyncClient, monkeypatch):
    """Degraded is not not-ready: with the database healthy an inventory edit
    is safe, and refusing it would turn a Redis blip into an outage."""
    _pin_dependencies(monkeypatch, db=True, redis=False)

    response = await client.post("/api/v1/hardware", json={"name": "nas"})

    # Rejected by authentication, not by admission control — the request
    # reached the router, which is the whole point.
    assert response.status_code != 503
    assert response.status_code in (401, 403)


async def test_a_write_is_refused_while_draining(client: AsyncClient, monkeypatch):
    """SRV-04: SIGTERM sets STOPPING, and admission stops at that moment rather
    than whenever a cached readiness verdict happens to expire."""
    _pin_dependencies(monkeypatch, db=True, redis=True)
    write_admission.arm()
    # Prime the cache while the process is still healthy: a drain that admits
    # "one last write" out of a stale cache is the bug this asserts against.
    await client.get("/api/v1/readyz")

    set_state(ServerState.STOPPING)
    response = await client.post("/api/v1/hardware", json={"name": "nas"})

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == write_admission.ERROR_CODE_DRAINING
    assert body["health"] == "stopping"


async def test_the_lifecycle_gate_only_fires_in_a_process_that_owns_its_lifecycle(
    client: AsyncClient, monkeypatch
):
    """An ASGI host that never runs the lifespan leaves the lifecycle state at
    its import-time default. Refusing every write in that process would be
    refusing on the strength of a state nothing is maintaining."""
    _pin_dependencies(monkeypatch, db=True, redis=True)
    write_admission.disarm()
    set_state(ServerState.STOPPING)

    response = await client.post("/api/v1/hardware", json={"name": "nas"})

    assert response.status_code != 503


async def test_health_endpoints_stay_reachable_while_writes_are_refused(
    client: AsyncClient, monkeypatch
):
    _pin_dependencies(monkeypatch, db=True, redis=True)
    write_admission.arm()
    set_state(ServerState.STOPPING)

    for path in ("/api/v1/livez", "/api/v1/startupz"):
        assert (await client.get(path)).status_code == 200
