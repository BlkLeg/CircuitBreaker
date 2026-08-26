"""Hardware telemetry endpoint tests.

The read paths take ``auth_headers`` alongside the write path: cd1724ff withdrew
the open first-run admin sentinel, so /hardware/{id}/telemetry answers 401 until
an admin exists and authenticates, reads included.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric


def test_get_telemetry_unconfigured_returns_200(client, db, auth_headers):
    hw = Hardware(name="telemetry-unconfigured", role="server")
    db.add(hw)
    db.commit()
    db.refresh(hw)

    resp = client.get(f"/api/v1/hardware/{hw.id}/telemetry", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert body["status"] == "unconfigured"
    assert body["source"] == "none"


def test_get_telemetry_falls_back_to_db_when_cache_read_fails(
    client, db, monkeypatch, auth_headers
):
    hw = Hardware(
        name="telemetry-db-fallback",
        role="server",
        telemetry_config={"profile": "snmp_generic", "host": "10.0.0.42", "enabled": True},
    )
    db.add(hw)
    db.flush()
    db.add(
        HardwareLiveMetric(
            hardware_id=hw.id,
            collected_at=utcnow(),
            status="healthy",
            raw={"cpu_pct": 42.5, "mem_pct": 55.1},
            source="collector",
        )
    )
    db.commit()

    monkeypatch.setattr(
        "app.services.telemetry_service.get_cached_telemetry",
        AsyncMock(side_effect=RuntimeError("redis unavailable")),
    )

    resp = client.get(f"/api/v1/hardware/{hw.id}/telemetry", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["source"] == "db"
    assert body["data"]["cpu_pct"] == 42.5


def test_manual_poll_writes_sample_and_updates_cache(client, db, monkeypatch, auth_headers):
    import app.services.telemetry_service as telemetry_service

    hw = Hardware(
        name="telemetry-manual-poll",
        role="server",
        telemetry_config={"profile": "snmp_generic", "host": "10.0.0.7", "enabled": True},
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)

    monkeypatch.setattr(
        "app.api.telemetry.poll_hardware",
        lambda _hw, _vault: {"status": "healthy", "data": {"cpu_pct": 17.2}},
    )
    cache_mock = AsyncMock()
    pub_mock = AsyncMock()
    monkeypatch.setattr(telemetry_service, "cache_telemetry", cache_mock)
    monkeypatch.setattr(telemetry_service, "publish_telemetry", pub_mock)

    resp = client.post(f"/api/v1/hardware/{hw.id}/telemetry/poll", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["data"]["cpu_pct"] == 17.2

    row = (
        db.query(HardwareLiveMetric)
        .filter(HardwareLiveMetric.hardware_id == hw.id)
        .order_by(HardwareLiveMetric.collected_at.desc())
        .first()
    )
    assert row is not None
    assert row.status == "healthy"
    assert row.raw["cpu_pct"] == 17.2

    db.refresh(hw)
    assert hw.telemetry_status == "healthy"
    assert hw.telemetry_data["cpu_pct"] == 17.2
    assert cache_mock.await_count >= 1
    assert pub_mock.await_count >= 1


def test_manual_poll_runs_the_device_call_off_the_event_loop(client, db, monkeypatch, auth_headers):
    """poll_hardware is synchronous and talks to the network, so it must not run inline.

    ``poll_now`` is an ``async def`` endpoint, which means anything it calls
    directly executes on the API process's event loop. ``poll_hardware`` reaches
    a device over SNMP/Redfish via blocking ``subprocess.run``/HTTP calls — the
    snmp_network_device profile alone can spend 105s in the kernel (three 5s
    ``snmpget`` calls plus nine 10s ``snmpwalk`` calls) before it gives up. On
    the loop that stalls *every* request the process is serving, not just this
    one, so the call has to be dispatched to a worker thread.

    We assert that by looking for a running loop from inside the patched poll:
    a worker thread has none, the loop thread does.
    """
    import app.services.telemetry_service as telemetry_service

    hw = Hardware(
        name="telemetry-offloop-poll",
        role="server",
        telemetry_config={"profile": "snmp_network_device", "host": "10.0.0.9", "enabled": True},
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)

    observed: dict[str, bool] = {}

    def _fake_poll_hardware(_hw, _vault):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            observed["ran_off_loop"] = True
        else:
            observed["ran_off_loop"] = False
        return {"status": "healthy", "data": {"cpu_pct": 3.5}}

    monkeypatch.setattr("app.api.telemetry.poll_hardware", _fake_poll_hardware)
    monkeypatch.setattr(telemetry_service, "cache_telemetry", AsyncMock())
    monkeypatch.setattr(telemetry_service, "publish_telemetry", AsyncMock())

    resp = client.post(f"/api/v1/hardware/{hw.id}/telemetry/poll", headers=auth_headers)
    assert resp.status_code == 200
    assert observed.get("ran_off_loop") is True, (
        "poll_hardware ran on the event loop thread — a slow device now blocks the whole API"
    )


def test_manual_poll_of_an_unreachable_device_times_out_as_unreachable(
    client, db, monkeypatch, auth_headers
):
    """An unreachable device must bound the request, not hold it open for minutes.

    The background collector already caps each device at
    CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS; the manual poll had no cap at all, so
    an admin pressing "poll now" on a dead host held a worker (and, before the
    off-loop fix, the loop) for as long as the underlying client took to fail.
    The timeout is floored at 5s, so this test pins the env var at that floor
    and has the patched poll sleep just past it.
    """
    import app.services.telemetry_service as telemetry_service

    hw = Hardware(
        name="telemetry-unreachable-poll",
        role="server",
        telemetry_config={"profile": "snmp_generic", "host": "10.0.0.99", "enabled": True},
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)

    monkeypatch.setenv("CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS", "5")

    def _hanging_poll_hardware(_hw, _vault):
        # Sleeps past the 5s cap. Kept short so the orphaned worker thread —
        # asyncio.to_thread cannot cancel it — retires promptly after teardown.
        time.sleep(6)
        return {"status": "healthy", "data": {"cpu_pct": 99.9}}

    monkeypatch.setattr("app.api.telemetry.poll_hardware", _hanging_poll_hardware)
    monkeypatch.setattr(telemetry_service, "cache_telemetry", AsyncMock())
    monkeypatch.setattr(telemetry_service, "publish_telemetry", AsyncMock())

    started = time.monotonic()
    resp = client.post(f"/api/v1/hardware/{hw.id}/telemetry/poll", headers=auth_headers)
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unreachable"
    assert elapsed < 6, f"request was not bounded by the timeout (took {elapsed:.1f}s)"

    db.refresh(hw)
    assert hw.telemetry_status == "unreachable"
