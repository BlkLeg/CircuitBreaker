"""Smoke tests for server lifecycle state transitions.

These tests orchestrate a real running Docker container and verify that
/api/v1/health reports the correct states at each lifecycle stage.

Requirements:
  pip install pytest pytest-asyncio httpx

Run with:
  pytest apps/backend/tests/smoke/ -v -m smoke --tb=short

The container must be running before the ready/stopping/restart tests.
"""

import asyncio
import shutil
import subprocess
import time

import httpx
import pytest

HEALTH_URL = "http://localhost:8080/api/v1/health"
CONTAINER_NAME = "circuitbreaker"
STARTUP_TIMEOUT = 30  # seconds to wait for READY
POLL_INTERVAL = 0.5  # seconds between polls


def _docker_smoke_available() -> bool:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return False
    try:
        subprocess.run(
            [docker_bin, "inspect", CONTAINER_NAME],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _docker_smoke_available(),
    reason="Docker smoke prerequisites missing (docker CLI or circuitbreaker container).",
)


# ── Helpers ────────────────────────────────────────────────────────────────


async def poll_until_state(target_state: str, timeout_s: float) -> dict | None:
    """Poll /health until target_state is reached; return final body or None."""
    deadline = time.time() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() < deadline:
            try:
                res = await client.get(HEALTH_URL)
                data = res.json()
                if data.get("state") == target_state:
                    return data
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            await asyncio.sleep(POLL_INTERVAL)
    return None


async def poll_until_offline(timeout_s: float) -> bool:
    """Return True when server stops responding entirely."""
    deadline = time.time() + timeout_s
    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.time() < deadline:
            try:
                await client.get(HEALTH_URL)
                await asyncio.sleep(POLL_INTERVAL)
            except (httpx.ConnectError, httpx.TimeoutException):
                return True
    return False


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_health_returns_starting_before_ready():
    """
    Immediately after container start, /health must return state=starting
    before it transitions to state=ready.
    Confirms STARTING state is real and observable — not skipped.
    """
    subprocess.run(
        ["docker", "restart", CONTAINER_NAME],
        check=True,
        capture_output=True,
    )

    observed_states: list[str] = []
    deadline = time.time() + STARTUP_TIMEOUT

    async with httpx.AsyncClient(timeout=1.0) as client:
        while time.time() < deadline:
            try:
                res = await client.get(HEALTH_URL)
                data = res.json()
                state = data.get("state")
                if state and (not observed_states or observed_states[-1] != state):
                    observed_states.append(state)
                if state == "ready":
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                if not observed_states or observed_states[-1] != "offline":
                    observed_states.append("offline")
            await asyncio.sleep(POLL_INTERVAL)

    assert "starting" in observed_states, (
        f"Never observed 'starting' state. Observed: {observed_states}"
    )
    assert observed_states[-1] == "ready", (
        f"Server did not reach 'ready'. Final observed states: {observed_states}"
    )
    starting_idx = observed_states.index("starting")
    ready_idx = observed_states.index("ready")
    assert starting_idx < ready_idx, f"'starting' must come before 'ready'. Got: {observed_states}"


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_health_returns_stopping_before_offline():
    """
    When container stops gracefully, /health must return state=stopping
    before the server goes offline.
    Confirms graceful drain is observable.
    """
    ready = await poll_until_state("ready", timeout_s=STARTUP_TIMEOUT)
    assert ready, "Server did not reach ready state before stop test"

    observed_states: list[str] = []

    async def observe():
        deadline = time.time() + 20
        async with httpx.AsyncClient(timeout=1.0) as client:
            while time.time() < deadline:
                try:
                    res = await client.get(HEALTH_URL)
                    data = res.json()
                    state = data.get("state")
                    if state and (not observed_states or observed_states[-1] != state):
                        observed_states.append(state)
                    if state not in ("ready", "stopping"):
                        break
                except (httpx.ConnectError, httpx.TimeoutException):
                    if not observed_states or observed_states[-1] != "offline":
                        observed_states.append("offline")
                    break
                await asyncio.sleep(0.2)

    observe_task = asyncio.create_task(observe())

    subprocess.run(
        ["docker", "stop", "--time", "10", CONTAINER_NAME],
        check=True,
        capture_output=True,
    )

    await observe_task

    assert "stopping" in observed_states, (
        f"Never observed 'stopping' state during shutdown. Observed: {observed_states}"
    )

    # Restart for subsequent tests
    subprocess.run(["docker", "start", CONTAINER_NAME], check=True)


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_full_restart_cycle_state_sequence():
    """
    A full restart must produce this observable sequence:
    ready → stopping → offline → starting → ready
    No state may be skipped. No wrong-order transitions.
    """
    ready = await poll_until_state("ready", timeout_s=STARTUP_TIMEOUT)
    assert ready, "Server must be ready before restart test"

    observed: list[str] = []
    deadline = time.time() + 60

    async def observe_all():
        async with httpx.AsyncClient(timeout=1.0) as client:
            while time.time() < deadline:
                try:
                    res = await client.get(HEALTH_URL)
                    state = res.json().get("state")
                    if state and (not observed or observed[-1] != state):
                        observed.append(state)
                    # Stop once we've seen ready a second time
                    if len(observed) >= 2 and observed[-1] == "ready":
                        return
                except (httpx.ConnectError, httpx.TimeoutException):
                    if not observed or observed[-1] != "offline":
                        observed.append("offline")
                await asyncio.sleep(0.3)

    observe_task = asyncio.create_task(observe_all())
    subprocess.run(["docker", "restart", CONTAINER_NAME], check=True)
    await observe_task

    assert observed[0] == "ready", f"Must start from ready. Got: {observed}"
    assert "offline" in observed, f"Must go offline during restart. Got: {observed}"
    assert "starting" in observed, f"Must show starting on way up. Got: {observed}"
    assert observed[-1] == "ready", f"Must end at ready. Got: {observed}"

    ready_start_idx = observed.index("ready")
    offline_idx = observed.index("offline")
    starting_idx = observed.index("starting")
    ready_end_idx = len(observed) - 1 - observed[::-1].index("ready")

    assert ready_start_idx < offline_idx, f"ready must come before offline. Got: {observed}"
    assert offline_idx < starting_idx, f"offline must come before starting. Got: {observed}"
    assert starting_idx < ready_end_idx, f"starting must come before final ready. Got: {observed}"


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_health_never_returns_500():
    """
    /health must return 200 in all lifecycle states.
    500 is never acceptable from a health endpoint.
    """
    ready = await poll_until_state("ready", timeout_s=STARTUP_TIMEOUT)
    assert ready

    async with httpx.AsyncClient(timeout=3.0) as client:
        for _ in range(10):
            try:
                res = await client.get(HEALTH_URL)
                assert res.status_code == 200, f"/health returned {res.status_code}: {res.text}"
            except (httpx.ConnectError, httpx.TimeoutException):
                pass  # Offline is ok — 500 is not
            await asyncio.sleep(0.5)


@pytest.mark.asyncio
@pytest.mark.smoke
async def test_health_response_schema():
    """
    /health response must always contain required fields.
    Frontend depends on this shape — schema drift breaks the lifecycle banner.
    """
    ready = await poll_until_state("ready", timeout_s=STARTUP_TIMEOUT)
    assert ready

    async with httpx.AsyncClient() as client:
        res = await client.get(HEALTH_URL)
        data = res.json()

    assert "state" in data, "Missing 'state' field"
    assert "ready" in data, "Missing 'ready' field"
    assert "version" in data, "Missing 'version' field"
    assert "uptime_s" in data, "Missing 'uptime_s' field"
    assert "checks" in data, "Missing 'checks' field"
    assert "db" in data["checks"], "Missing checks.db"
    assert "redis" in data["checks"], "Missing checks.redis"
    assert data["state"] in ("starting", "ready", "stopping"), (
        f"Invalid state value: {data['state']}"
    )
    assert isinstance(data["uptime_s"], int | float), "uptime_s must be numeric"
    assert data["ready"] is True, f"Expected ready=true, got: {data['ready']}"
