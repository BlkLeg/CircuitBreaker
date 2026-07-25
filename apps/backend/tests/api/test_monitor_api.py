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
    assert uptime.json() == {"pct_24h": None}
    history = await client.get(f"/api/v1/monitors/{mid}/history", headers=auth_headers)
    assert history.json() == []
