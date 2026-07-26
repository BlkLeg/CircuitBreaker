from datetime import UTC, datetime, timedelta

import pytest


async def _create(client, auth_headers, **overrides):
    payload = {
        "name": "edge web",
        "check_type": "http",
        "host": "192.0.2.7",
        "config": {"url": "http://192.0.2.7/health", "accepted_statuses": ["200-299"]},
        "interval_secs": 60,
        "max_retries": 2,
    }
    payload.update(overrides)
    return await client.post("/api/v1/monitors", headers=auth_headers, json=payload)


@pytest.mark.asyncio
async def test_create_and_get(client, auth_headers):
    resp = await _create(client, auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["config"]["url"] == "http://192.0.2.7/health"

    got = await client.get(f"/api/v1/monitors/{body['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["name"] == "edge web"


@pytest.mark.asyncio
async def test_create_invalid_config_422(client, auth_headers):
    resp = await _create(client, auth_headers, config={"nonsense": True})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_filter(client, auth_headers):
    await _create(client, auth_headers, name="linked", target_type="hardware", target_id=1)
    resp = await client.get(
        "/api/v1/monitors",
        headers=auth_headers,
        params={"target_type": "hardware", "target_id": 1},
    )
    assert resp.status_code == 200
    assert all(m["target_type"] == "hardware" for m in resp.json())


@pytest.mark.asyncio
async def test_pause_resume(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    paused = await client.post(f"/api/v1/monitors/{mid}/pause", headers=auth_headers)
    assert paused.json()["enabled"] is False
    resumed = await client.post(f"/api/v1/monitors/{mid}/resume", headers=auth_headers)
    assert resumed.json()["enabled"] is True
    events = (await client.get(f"/api/v1/monitors/{mid}/events", headers=auth_headers)).json()
    assert {e["event_type"] for e in events} >= {"paused", "resumed"}


@pytest.mark.asyncio
async def test_missing_monitor_404(client, auth_headers):
    assert (await client.get("/api/v1/monitors/999999", headers=auth_headers)).status_code == 404
    assert (await client.delete("/api/v1/monitors/999999", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_uptime_and_history_empty_ok(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    uptime = await client.get(f"/api/v1/monitors/{mid}/uptime", headers=auth_headers)
    assert uptime.json() == {
        "pct_24h": None,
        "pct_7d": None,
        "pct_30d": None,
        "pct_365d": None,
        "pct_total": None,
        "last_polled_at": None,
    }
    history = await client.get(f"/api/v1/monitors/{mid}/history", headers=auth_headers)
    assert history.json() == []


# ── Target-scoped routes (inventory pages, drawers, map) ─────────────────────


@pytest.mark.asyncio
async def test_target_quick_monitor_hardware(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.50")
    resp = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["target_type"] == "hardware" and body["target_id"] == hw.id

    # idempotent per (hardware, check_type)
    again = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    assert again.json()["id"] == body["id"]

    for action in ("pause", "resume", "check"):
        resp = await client.post(
            f"/api/v1/monitors/target/hardware/{hw.id}/{action}", headers=auth_headers
        )
        assert resp.status_code == 200, action


@pytest.mark.asyncio
async def test_target_quick_monitor_missing_404(client, auth_headers):
    assert (
        await client.post("/api/v1/monitors/target/hardware/999999", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/hardware/999999/pause", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_target_quick_monitor_compute_unit(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.60")
    cu = factories.compute_unit(hardware_id=hw.id, ip_address="192.0.2.61")

    resp = await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["target_type"] == "compute_unit" and body["target_id"] == cu.id

    # idempotent
    again = await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)
    assert again.json()["id"] == body["id"]

    for action in ("pause", "resume", "check"):
        resp = await client.post(
            f"/api/v1/monitors/target/compute_unit/{cu.id}/{action}", headers=auth_headers
        )
        assert resp.status_code == 200, action


@pytest.mark.asyncio
async def test_target_quick_monitor_service_uses_http(client, auth_headers, factories):
    svc = factories.service(name="grafana", url="https://grafana.lan/login")
    resp = await client.post(f"/api/v1/monitors/target/service/{svc.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "http"
    assert body["host"] == "grafana.lan"
    assert body["config"] == {"url": "https://grafana.lan/login"}


@pytest.mark.asyncio
async def test_target_quick_monitor_external_node(client, auth_headers, factories):
    node = factories.external_node(ip_address="api.example.com")
    resp = await client.post(
        f"/api/v1/monitors/target/external_node/{node.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["host"] == "api.example.com"
    assert body["target_type"] == "external_node" and body["target_id"] == node.id

    summary = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "external_node"},
    )
    assert [r["target_id"] for r in summary.json()] == [node.id]


@pytest.mark.asyncio
async def test_target_quick_monitor_accepts_overrides(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.62")
    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}",
        headers=auth_headers,
        json={"check_type": "tcp", "config": {"port": 22}},
    )
    assert resp.status_code == 200
    assert resp.json()["check_type"] == "tcp"
    assert resp.json()["config"] == {"port": 22}


@pytest.mark.asyncio
async def test_target_quick_monitor_invalid_config_422(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.63")
    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}",
        headers=auth_headers,
        json={"check_type": "tcp", "config": {"bogus": 1}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_unknown_type_422(client, auth_headers):
    resp = await client.post("/api/v1/monitors/target/nonsense/1", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_unprobeable_404(client, auth_headers, factories):
    svc = factories.service(name="no-address")
    assert (
        await client.post(f"/api/v1/monitors/target/service/{svc.id}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/compute_unit/999999", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/service/999999/pause", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_target_summary(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.64")
    cu = factories.compute_unit(hardware_id=hw.id, ip_address="192.0.2.65")
    await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)

    resp = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "compute_unit"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["target_id"] == cu.id
    assert rows[0]["enabled"] is True
    assert rows[0]["status"] == "pending"
    assert rows[0]["monitor_ids"] == [rows[0]["monitor_id"]]

    scoped = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "compute_unit", "target_ids": [999999]},
    )
    assert scoped.json() == []

    bad = await client.get(
        "/api/v1/monitors/target-summary", headers=auth_headers, params={"target_type": "nope"}
    )
    assert bad.status_code == 422


# ── Overview (the dashboard's single fetch) ──────────────────────────────────


def _sample(mid, value, ts):
    from app.db.models import TelemetryTimeseries

    return TelemetryTimeseries(
        entity_type="monitor",
        entity_id=0,
        item_id=mid,
        metric="latency_ms",
        value=value,
        source="monitor",
        ts=ts,
    )


def _event(mid, status, msg, ts):
    from app.db.models import MonitorEvent

    return MonitorEvent(item_id=mid, event_type=status, status_to=status, msg=msg, created_at=ts)


@pytest.mark.asyncio
async def test_overview_includes_series_and_checks(client, auth_headers, db_session):
    mid = (await _create(client, auth_headers, name="overview-target")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i, value in enumerate([10.0, 20.0, 30.0]):
        db_session.add(_sample(mid, value, base + timedelta(minutes=i)))
    for i, status in enumerate(["up", "down", "up"]):
        db_session.add(_event(mid, status, f"event {i}", base + timedelta(minutes=i)))
    db_session.commit()

    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == mid)

    # every MonitorRead field the page renders is still present
    assert row["name"] == "overview-target"
    assert row["check_type"] == "http"
    assert row["status"] == "pending"

    # latency series is oldest → newest, for the sparkline
    assert row["latency_series"] == [10.0, 20.0, 30.0]

    # checks are newest first, matching GET /events and CheckHistoryBar
    assert [c["msg"] for c in row["recent_checks"]] == ["event 2", "event 1", "event 0"]
    assert row["recent_checks"][0]["status_to"] == "up"
    assert set(row["recent_checks"][0]) == {"id", "status_to", "msg", "created_at"}


@pytest.mark.asyncio
async def test_overview_caps_series_lengths(client, auth_headers, db_session):
    mid = (await _create(client, auth_headers, name="chatty")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i in range(30):
        db_session.add(_sample(mid, float(i), base + timedelta(seconds=i)))
        db_session.add(_event(mid, "up", f"e{i}", base + timedelta(seconds=i)))
    db_session.commit()

    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert len(row["latency_series"]) == 12
    assert row["latency_series"] == [float(i) for i in range(18, 30)]  # newest 12, oldest first
    assert len(row["recent_checks"]) == 20
    assert row["recent_checks"][0]["msg"] == "e29"  # newest first


@pytest.mark.asyncio
async def test_overview_empty_series_for_fresh_monitor(client, auth_headers):
    mid = (await _create(client, auth_headers, name="fresh")).json()["id"]
    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert row["latency_series"] == []
    assert row["recent_checks"] == []


@pytest.mark.asyncio
async def test_overview_route_wins_over_monitor_id(client, auth_headers):
    """ "/overview" must not be parsed as a monitor id."""
    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
