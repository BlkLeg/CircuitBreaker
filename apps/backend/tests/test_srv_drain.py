"""SRV-04: SIGTERM drains safely, and the drain starts by closing admission.

A graceful shutdown that keeps accepting writes while it tears its workers down
is not graceful — it accepts work it has already decided not to finish. The
order the lifespan shuts down in is therefore a contract, and this suite runs
the real lifespan (the same one uvicorn drives on SIGTERM) and observes it from
inside, rather than asserting on the source.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import health, write_admission
from app.core.server_state import ServerState, get_state, set_state


@pytest.fixture(autouse=True)
def _restore_process_state():
    previous_state = get_state()
    previous_armed = write_admission.is_armed()
    yield
    set_state(previous_state)
    health.reset_cache()
    if previous_armed:
        write_admission.arm()
    else:
        write_admission.disarm()


@pytest.fixture
def lifespan_env(db_session):
    """The environment a real lifespan needs on this host.

    Mirrors tests/conftest.py::ws_client, which is the suite's existing way of
    running the full lifespan: `/data` is not writable outside a container, and
    nats-py retries its *initial* connect forever when no broker is reachable,
    which would hang startup on a concern unrelated to draining.
    """
    from app.core.nats_client import nats_client
    from app.db.session import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    original_connect = nats_client.connect
    old_data_dir = os.environ.get("CB_DATA_DIR")
    with tempfile.TemporaryDirectory() as tmp_data_dir:
        try:
            app.dependency_overrides[get_db] = override_get_db
            nats_client.connect = AsyncMock(return_value=None)
            os.environ["CB_DATA_DIR"] = tmp_data_dir
            yield app
        finally:
            app.dependency_overrides.pop(get_db, None)
            nats_client.connect = original_connect
            if old_data_dir is None:
                os.environ.pop("CB_DATA_DIR", None)
            else:
                os.environ["CB_DATA_DIR"] = old_data_dir


async def test_the_drain_closes_admission_before_it_tears_anything_down(lifespan_env, monkeypatch):
    """The first thing shutdown does is stop taking work.

    Observed at the first step of the teardown sequence: by the time the
    listener is asked to stop, the server must already be refusing writes. If
    admission closed later — after the scheduler's ten-second grace period, say
    — every write admitted in between would be accepted by a process that is
    on its way out."""
    app = lifespan_env
    observed: dict[str, object] = {}

    from app.services import listener_service as listener_module

    original_stop = listener_module.listener_service.stop

    async def _recording_stop():
        snapshot = await health.current_health(max_age_s=0.0)
        observed["state"] = snapshot.state.value
        observed["writes_permitted"] = snapshot.writes_permitted
        observed["armed"] = write_admission.is_armed()
        return await original_stop()

    monkeypatch.setattr(listener_module.listener_service, "stop", _recording_stop)

    async with app.router.lifespan_context(app):
        assert get_state() is ServerState.READY
        assert write_admission.is_armed(), "the lifespan must own the lifecycle gate"

    assert observed, "shutdown never reached the listener teardown"
    assert observed["state"] == "stopping"
    assert observed["writes_permitted"] is False
    assert observed["armed"] is True


async def test_a_write_arriving_mid_drain_is_refused(lifespan_env, monkeypatch):
    """The same guarantee from the client's side: the request that races the
    shutdown gets a 503 it can retry against the replacement instance, not a
    half-applied write."""
    app = lifespan_env
    responses: dict[str, int] = {}

    from app.services import listener_service as listener_module

    original_stop = listener_module.listener_service.stop

    async def _write_during_drain():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
        ) as client:
            response = await client.post("/api/v1/hardware", json={"name": "nas"})
            responses["mid_drain"] = response.status_code
            responses["code"] = response.json().get("error_code")
        return await original_stop()

    monkeypatch.setattr(listener_module.listener_service, "stop", _write_during_drain)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
        ) as client:
            # While running, the same request is not refused by admission
            # control — it is refused by authentication, having reached the
            # router.
            live = await client.post("/api/v1/hardware", json={"name": "nas"})
            assert live.status_code in (401, 403)

    assert responses["mid_drain"] == 503
    assert responses["code"] == write_admission.ERROR_CODE_DRAINING


async def test_the_drain_leaves_nothing_running(lifespan_env):
    """Leases hand off only if the process that held them actually lets go: an
    in-process worker still running after shutdown is a second owner competing
    with the replacement instance."""
    app = lifespan_env
    before = asyncio.all_tasks()

    async with app.router.lifespan_context(app):
        pass

    leaked = [
        task
        for task in asyncio.all_tasks()
        if task not in before and not task.done() and task is not asyncio.current_task()
    ]
    assert leaked == [], f"tasks survived the drain: {[t.get_name() for t in leaked]}"

    from app.core.scheduler import get_scheduler

    assert get_scheduler().running is False, "the scheduler outlived the drain"
    assert write_admission.is_armed() is False, "the lifecycle gate outlived the lifecycle"


async def test_a_restarted_process_can_take_the_lease_the_old_one_held(lifespan_env):
    """The rolling-restart case: whatever the departing process held must be
    acquirable by the next one, or the function stops running entirely."""
    app = lifespan_env

    async with app.router.lifespan_context(app):
        pass

    from app.core.job_lock import _lock_id_for, advisory_unlock, lock_session, try_advisory_lock

    # Two namespaces, not one. `scheduled_job` covers the APScheduler jobs; the
    # in-process worker loops take their own leases under `worker_lease`
    # (app/workers/__init__.py, SingleActiveLease). This test checked only the
    # first for long enough that the second was leaking in CI as an intermittent
    # failure of tests/test_worker_lease.py two files later in the same shard --
    # a test named for the rolling-restart case that did not probe the leases a
    # rolling restart actually contends for.
    leases = [
        ("scheduled_job", job) for job in ("pg_backup", "retention_job", "integration_sync_job")
    ]
    leases += [("worker_lease", worker) for worker in ("integration_sync", "telemetry_collector")]

    probe = lock_session()
    try:
        for namespace, job_id in leases:
            lock_id = _lock_id_for(namespace, job_id)
            assert try_advisory_lock(probe, lock_id), (
                f"{namespace}/{job_id} lease was never released — a replacement process "
                f"would stand by forever and this function would stop running"
            )
            advisory_unlock(probe, lock_id)
    finally:
        probe.close()
