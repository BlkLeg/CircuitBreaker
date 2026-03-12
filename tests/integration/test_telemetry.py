from __future__ import annotations

from unittest.mock import AsyncMock

from app.core.time import utcnow
from app.db.models import Hardware, HardwareLiveMetric


def test_get_telemetry_unconfigured_returns_200(client, db):
    hw = Hardware(name="telemetry-unconfigured", role="server")
    db.add(hw)
    db.commit()
    db.refresh(hw)

    resp = client.get(f"/api/v1/hardware/{hw.id}/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert body["status"] == "unconfigured"
    assert body["source"] == "none"


def test_get_telemetry_falls_back_to_db_when_cache_read_fails(client, db, monkeypatch):
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

    resp = client.get(f"/api/v1/hardware/{hw.id}/telemetry")
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
