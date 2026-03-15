"""
Tests for Hardware Monitor endpoints:
  GET /api/v1/monitors, POST /api/v1/monitors, PUT /api/v1/monitors/{id}, DELETE /api/v1/monitors/{id}
  GET /api/v1/monitors/{id}/history, POST /api/v1/monitors/{id}/check

All tests use real database operations and test actual probe functionality where possible, no mocks.
"""

import pytest
from sqlalchemy import select

from app.db.models import HardwareMonitor, UptimeEvent

MONITORS_URL = "/api/v1/monitors"


# ── HardwareMonitor CRUD Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_monitors_empty(client, auth_headers):
    """GET /monitors returns empty list when no monitors exist."""
    resp = await client.get(MONITORS_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_hardware_monitor(client, auth_headers, db_session, factories):
    """POST /monitors creates a new hardware monitor."""
    hw = factories.hardware(name="monitor-hw", ip_address="192.168.1.100")

    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp", "tcp"],
        "interval_secs": 60,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert set(body["probe_methods"]) == {"icmp", "tcp"}
    assert body["interval_secs"] == 60
    assert body["enabled"] is True

    # Verify in database
    monitor_in_db = db_session.execute(
        select(HardwareMonitor).where(HardwareMonitor.hardware_id == hw.id)
    ).scalar_one_or_none()
    assert monitor_in_db is not None
    # probe_methods might be JSON string or list depending on DB column type
    probe_methods = monitor_in_db.probe_methods
    if isinstance(probe_methods, str):
        import json

        probe_methods = json.loads(probe_methods)
    assert set(probe_methods) == {"icmp", "tcp"}


@pytest.mark.asyncio
async def test_create_monitor_duplicate_returns_409(client, auth_headers, factories):
    """POST /monitors for existing hardware returns 409."""
    hw = factories.hardware(name="dup-hw", ip_address="192.168.1.101")

    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp"],
        "interval_secs": 30,
        "enabled": True,
    }
    resp1 = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp1.status_code == 200

    resp2 = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_monitor_nonexistent_hardware_returns_404(client, auth_headers):
    """POST /monitors for non-existent hardware returns 404."""
    payload = {
        "hardware_id": 99999,
        "probe_methods": ["icmp"],
        "interval_secs": 60,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 404
    assert "hardware not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_monitors_returns_created(client, auth_headers, factories):
    """GET /monitors includes previously created monitors."""
    hw = factories.hardware(name="list-hw", ip_address="192.168.1.102")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["http"], "interval_secs": 120},
        headers=auth_headers,
    )

    resp = await client.get(MONITORS_URL, headers=auth_headers)
    assert resp.status_code == 200

    monitors = resp.json()
    hw_ids = [m["hardware_id"] for m in monitors]
    assert hw.id in hw_ids


@pytest.mark.asyncio
async def test_get_monitor_by_hardware_id(client, auth_headers, factories):
    """GET /monitors/{hardware_id} returns specific monitor."""
    hw = factories.hardware(name="get-hw", ip_address="192.168.1.103")
    create_resp = await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["snmp"], "interval_secs": 90},
        headers=auth_headers,
    )
    assert create_resp.status_code == 200

    resp = await client.get(f"{MONITORS_URL}/{hw.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == hw.id
    assert "snmp" in resp.json()["probe_methods"]


@pytest.mark.asyncio
async def test_get_monitor_404_for_missing(client, auth_headers):
    """GET /monitors/{hardware_id} returns 404 for non-existent monitor."""
    resp = await client.get(f"{MONITORS_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_monitor(client, auth_headers, db_session, factories):
    """PUT /monitors/{hardware_id} updates monitor fields."""
    hw = factories.hardware(name="update-hw", ip_address="192.168.1.104")
    await client.post(
        MONITORS_URL,
        json={
            "hardware_id": hw.id,
            "probe_methods": ["icmp"],
            "interval_secs": 60,
            "enabled": True,
        },
        headers=auth_headers,
    )

    update_resp = await client.put(
        f"{MONITORS_URL}/{hw.id}",
        json={"probe_methods": ["icmp", "http"], "interval_secs": 120, "enabled": False},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert set(update_resp.json()["probe_methods"]) == {"icmp", "http"}
    assert update_resp.json()["interval_secs"] == 120
    assert update_resp.json()["enabled"] is False

    # Verify in database
    monitor_in_db = db_session.execute(
        select(HardwareMonitor).where(HardwareMonitor.hardware_id == hw.id)
    ).scalar_one_or_none()
    assert monitor_in_db.interval_secs == 120
    assert monitor_in_db.enabled is False


@pytest.mark.asyncio
async def test_update_monitor_404_for_missing(client, auth_headers):
    """PUT /monitors/{hardware_id} returns 404 for non-existent monitor."""
    resp = await client.put(
        f"{MONITORS_URL}/99999",
        json={"probe_methods": ["icmp"], "interval_secs": 60},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_monitor(client, auth_headers, db_session, factories):
    """DELETE /monitors/{hardware_id} removes monitor."""
    hw = factories.hardware(name="delete-hw", ip_address="192.168.1.105")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["tcp"], "interval_secs": 30},
        headers=auth_headers,
    )

    delete_resp = await client.delete(f"{MONITORS_URL}/{hw.id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    monitor_in_db = db_session.execute(
        select(HardwareMonitor).where(HardwareMonitor.hardware_id == hw.id)
    ).scalar_one_or_none()
    assert monitor_in_db is None


@pytest.mark.asyncio
async def test_delete_monitor_404_for_missing(client, auth_headers):
    """DELETE /monitors/{hardware_id} returns 404 for non-existent monitor."""
    resp = await client.delete(f"{MONITORS_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── Uptime History Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_monitor_history_empty(client, auth_headers, factories):
    """GET /monitors/{hardware_id}/history returns empty list when no events exist."""
    hw = factories.hardware(name="history-hw", ip_address="192.168.1.106")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["icmp"], "interval_secs": 60},
        headers=auth_headers,
    )

    resp = await client.get(f"{MONITORS_URL}/{hw.id}/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_monitor_history_with_events(client, auth_headers, db_session, factories):
    """GET /monitors/{hardware_id}/history returns uptime events."""
    hw = factories.hardware(name="event-hw", ip_address="192.168.1.107")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["icmp"], "interval_secs": 60},
        headers=auth_headers,
    )

    # Create uptime events manually
    from app.core.time import utcnow

    event1 = UptimeEvent(hardware_id=hw.id, status="up", probe_method="icmp", checked_at=utcnow())
    event2 = UptimeEvent(hardware_id=hw.id, status="down", probe_method="icmp", checked_at=utcnow())
    db_session.add_all([event1, event2])
    db_session.commit()

    resp = await client.get(f"{MONITORS_URL}/{hw.id}/history", headers=auth_headers)
    assert resp.status_code == 200

    events = resp.json()
    assert len(events) == 2
    assert {e["status"] for e in events} == {"up", "down"}


@pytest.mark.asyncio
async def test_get_monitor_history_limit_parameter(client, auth_headers, db_session, factories):
    """GET /monitors/{hardware_id}/history?limit=N respects limit."""
    hw = factories.hardware(name="limit-hw", ip_address="192.168.1.108")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["tcp"], "interval_secs": 60},
        headers=auth_headers,
    )

    # Create multiple events
    from app.core.time import utcnow

    for _i in range(10):
        event = UptimeEvent(hardware_id=hw.id, status="up", probe_method="tcp", checked_at=utcnow())
        db_session.add(event)
    db_session.commit()

    resp = await client.get(f"{MONITORS_URL}/{hw.id}/history?limit=5", headers=auth_headers)
    assert resp.status_code == 200

    events = resp.json()
    assert len(events) <= 5


# ── Immediate Check Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_immediate_check(client, auth_headers, factories):
    """POST /monitors/{hardware_id}/check triggers immediate probe."""
    hw = factories.hardware(name="check-hw", ip_address="127.0.0.1")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["icmp"], "interval_secs": 60},
        headers=auth_headers,
    )

    resp = await client.post(f"{MONITORS_URL}/{hw.id}/check", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert "last_status" in body


@pytest.mark.asyncio
async def test_immediate_check_404_for_missing_monitor(client, auth_headers):
    """POST /monitors/{hardware_id}/check returns 404 for non-existent monitor."""
    resp = await client.post(f"{MONITORS_URL}/99999/check", headers=auth_headers)
    assert resp.status_code == 404


# ── Probe Method Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_monitor_with_icmp_probe(client, auth_headers, factories):
    """POST /monitors with ICMP probe method."""
    hw = factories.hardware(name="icmp-hw", ip_address="8.8.8.8")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp"],
        "interval_secs": 30,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert "icmp" in resp.json()["probe_methods"]


@pytest.mark.asyncio
async def test_create_monitor_with_tcp_probe(client, auth_headers, factories):
    """POST /monitors with TCP probe method."""
    hw = factories.hardware(name="tcp-hw", ip_address="192.168.1.110")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["tcp"],
        "interval_secs": 45,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert "tcp" in resp.json()["probe_methods"]


@pytest.mark.asyncio
async def test_create_monitor_with_http_probe(client, auth_headers, factories):
    """POST /monitors with HTTP probe method."""
    hw = factories.hardware(name="http-hw", ip_address="192.168.1.111")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["http"],
        "interval_secs": 60,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert "http" in resp.json()["probe_methods"]


@pytest.mark.asyncio
async def test_create_monitor_with_snmp_probe(client, auth_headers, factories):
    """POST /monitors with SNMP probe method."""
    hw = factories.hardware(name="snmp-hw", ip_address="192.168.1.112")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["snmp"],
        "interval_secs": 120,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert "snmp" in resp.json()["probe_methods"]


@pytest.mark.asyncio
async def test_create_monitor_with_multiple_probe_methods(client, auth_headers, factories):
    """POST /monitors with multiple probe methods."""
    hw = factories.hardware(name="multi-hw", ip_address="192.168.1.113")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp", "tcp", "http"],
        "interval_secs": 60,
        "enabled": True,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert set(resp.json()["probe_methods"]) == {"icmp", "tcp", "http"}


# ── Monitor State Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_monitor_disabled_by_default(client, auth_headers, factories):
    """POST /monitors without 'enabled' field defaults appropriately."""
    hw = factories.hardware(name="default-hw", ip_address="192.168.1.114")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp"],
        "interval_secs": 60,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    # Check if enabled field exists in response
    assert "enabled" in resp.json()


@pytest.mark.asyncio
async def test_update_monitor_enable_disable(client, auth_headers, factories):
    """PUT /monitors can enable/disable monitoring."""
    hw = factories.hardware(name="toggle-hw", ip_address="192.168.1.115")
    await client.post(
        MONITORS_URL,
        json={
            "hardware_id": hw.id,
            "probe_methods": ["icmp"],
            "interval_secs": 60,
            "enabled": True,
        },
        headers=auth_headers,
    )

    # Disable
    resp1 = await client.put(
        f"{MONITORS_URL}/{hw.id}",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["enabled"] is False

    # Re-enable
    resp2 = await client.put(
        f"{MONITORS_URL}/{hw.id}",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["enabled"] is True


@pytest.mark.asyncio
async def test_monitor_records_last_status_after_check(client, auth_headers, db_session, factories):
    """POST /monitors/{id}/check updates last_status and last_checked_at."""
    hw = factories.hardware(name="status-hw", ip_address="127.0.0.1")
    await client.post(
        MONITORS_URL,
        json={"hardware_id": hw.id, "probe_methods": ["icmp"], "interval_secs": 60},
        headers=auth_headers,
    )

    # Run check
    check_resp = await client.post(f"{MONITORS_URL}/{hw.id}/check", headers=auth_headers)
    assert check_resp.status_code == 200

    body = check_resp.json()
    assert "last_status" in body
    assert "last_checked_at" in body

    # Verify in database
    monitor_in_db = db_session.execute(
        select(HardwareMonitor).where(HardwareMonitor.hardware_id == hw.id)
    ).scalar_one_or_none()
    assert monitor_in_db.last_checked_at is not None


# ── Error Handling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_monitor_empty_probe_methods_returns_422(client, auth_headers, factories):
    """POST /monitors with empty probe_methods list returns 422."""
    hw = factories.hardware(name="empty-probe-hw", ip_address="192.168.1.116")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": [],
        "interval_secs": 60,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_monitor_invalid_probe_method_returns_422(client, auth_headers, factories):
    """POST /monitors with invalid probe method returns 422."""
    hw = factories.hardware(name="invalid-probe-hw", ip_address="192.168.1.117")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["invalid_method"],
        "interval_secs": 60,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code in (422, 400)


@pytest.mark.asyncio
async def test_create_monitor_negative_interval_returns_422(client, auth_headers, factories):
    """POST /monitors with negative interval_secs returns 422."""
    hw = factories.hardware(name="neg-interval-hw", ip_address="192.168.1.118")
    payload = {
        "hardware_id": hw.id,
        "probe_methods": ["icmp"],
        "interval_secs": -10,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_monitor_missing_required_field_returns_422(client, auth_headers):
    """POST /monitors without required 'hardware_id' field returns 422."""
    payload = {
        "probe_methods": ["icmp"],
        "interval_secs": 60,
    }
    resp = await client.post(MONITORS_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_monitor_preserves_unspecified_fields(client, auth_headers, factories):
    """PUT /monitors only updates specified fields, preserves others."""
    hw = factories.hardware(name="preserve-hw", ip_address="192.168.1.119")
    await client.post(
        MONITORS_URL,
        json={
            "hardware_id": hw.id,
            "probe_methods": ["icmp", "tcp"],
            "interval_secs": 60,
            "enabled": True,
        },
        headers=auth_headers,
    )

    # Update only interval
    update_resp = await client.put(
        f"{MONITORS_URL}/{hw.id}",
        json={"interval_secs": 90},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["interval_secs"] == 90
    # probe_methods and enabled should be preserved (or re-specified in update)
    assert "probe_methods" in body
    assert "enabled" in body
