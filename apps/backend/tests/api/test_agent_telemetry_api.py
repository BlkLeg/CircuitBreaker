"""The two viewer-facing agent telemetry endpoints:
`GET /api/v1/agents/{id}/telemetry` and `.../telemetry/history`.

Neither had any coverage before Task 4 of
`plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import utcnow

_SUMMARY_KEYS = {
    "cpu_pct",
    "mem_pct",
    "root_disk_pct",
    "net_rx_bps",
    "net_tx_bps",
    "max_temp_c",
    "load_1",
    "uptime_s",
}

# Bucket width per range, mirroring api/agents.py's `bucket_widths`. Task 7
# widens these (D-2); the samples below are spaced far enough apart that every
# sample still lands in its own bucket under either table.
_RANGE_DURATION_S = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}


@pytest.mark.asyncio
async def test_telemetry_requires_authentication(client, factories):
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_telemetry_unknown_agent_returns_404(client, viewer_headers):
    resp = await client.get("/api/v1/agents/999999/telemetry", headers=viewer_headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent not found"


@pytest.mark.asyncio
async def test_telemetry_without_samples_returns_null_latest_and_empty_readiness(
    client, factories, viewer_headers
):
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["latest"] is None
    assert body["readiness"] == []
    assert body["hardware_id"] is None


@pytest.mark.asyncio
async def test_telemetry_returns_newest_sample_with_the_eight_summary_keys(
    client, factories, viewer_headers
):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)
    now = utcnow()
    # Insert the NEWEST row first so insertion (id) order is the reverse of
    # collected_at order: an endpoint that ordered by id would return the wrong
    # row and fail here.
    newest = factories.agent_host_sample(
        agent,
        sample_id="2" * 32,
        collected_at=now,
        status="degraded",
        cpu_pct=42.5,
        mem_pct=51.0,
        root_disk_pct=12.0,
        net_rx_bps=100.0,
        net_tx_bps=200.0,
        max_temp_c=48.0,
        load_1=0.5,
        uptime_s=1234,
        projected_at=now,
    )
    factories.agent_host_sample(
        agent, sample_id="1" * 32, collected_at=now - timedelta(minutes=5), cpu_pct=10.0
    )

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)

    assert resp.status_code == 200
    latest = resp.json()["latest"]
    assert latest["sample_id"] == newest.sample_id
    assert latest["status"] == "degraded"
    assert latest["projected"] is True
    assert set(latest["summary"]) == _SUMMARY_KEYS
    assert latest["summary"]["cpu_pct"] == 42.5
    assert latest["summary"]["uptime_s"] == 1234
    assert latest["payload"] == newest.raw
    assert resp.json()["hardware_id"] == hardware.id


@pytest.mark.asyncio
async def test_telemetry_readiness_is_sorted_by_collector(client, factories, viewer_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_readiness(agent, collector="host.docker", state="unavailable")
    factories.agent_capability_readiness(agent, collector="host.core", state="ready")
    factories.agent_capability_readiness(
        agent,
        collector="host.hwmon",
        state="degraded",
        reason="no sensors",
        remediation="install lm-sensors",
        missing=["/sys/class/hwmon"],
    )

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)

    assert resp.status_code == 200
    readiness = resp.json()["readiness"]
    assert [r["collector"] for r in readiness] == ["host.core", "host.docker", "host.hwmon"]
    assert readiness[2] | {"updated_at": None} == {
        "collector": "host.hwmon",
        "state": "degraded",
        "reason": "no sensors",
        "remediation": "install lm-sensors",
        "missing": ["/sys/class/hwmon"],
        "updated_at": None,
    }


@pytest.mark.asyncio
async def test_telemetry_capability_defaults_to_disabled_without_a_grant_row(
    client, factories, viewer_headers
):
    """No grant row is a denial, never a fallback to `default_enabled`."""
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)

    assert resp.status_code == 200
    assert resp.json()["capability"] == {"enabled": False, "config": {}}


@pytest.mark.asyncio
async def test_telemetry_capability_reports_the_granted_structured_shape(
    client, factories, viewer_headers
):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry", headers=viewer_headers)

    capability = resp.json()["capability"]
    assert capability["enabled"] is True
    assert capability["config"]["interval_s"] == 30


# ── history ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_rejects_an_unknown_range(client, factories, viewer_headers):
    agent = factories.agent(status="active")

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range=90d", headers=viewer_headers
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_history_with_no_data_returns_empty_points(client, factories, viewer_headers):
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry/history", headers=viewer_headers)

    assert resp.status_code == 200
    assert resp.json() == {"range": "1h", "points": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("range_name", ["1h", "6h", "24h", "7d", "30d"])
async def test_history_is_bounded_for_every_range(client, factories, viewer_headers, range_name):
    """Every range must stay bounded regardless of how many raw samples exist.

    Task 7 (D-2) replaces the universal 120 cap with per-range caps
    (1h:120, 6h:360, 24h:288, 7d:336, 30d:720) and rewrites this assertion to
    the per-range table. Deliberately *not* "exactly 120 preserving endpoints":
    that is the behavior Task 7 changes.
    """
    agent = factories.agent(status="active")
    now = utcnow()
    spacing = _RANGE_DURATION_S[range_name] // 145
    for index in range(130):
        factories.agent_host_sample(
            agent,
            sample_id=f"{index:032x}",
            collected_at=now - timedelta(seconds=spacing * (129 - index)),
            cpu_pct=float(index),
        )

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/telemetry/history?range={range_name}", headers=viewer_headers
    )

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert 2 <= len(points) <= 120
    assert all(set(p["summary"]) == _SUMMARY_KEYS for p in points)


@pytest.mark.asyncio
async def test_history_bucket_of_only_nulls_yields_none_not_zero(client, factories, viewer_headers):
    """A collector that reported nothing must render as a gap, not as 0 —
    a 0 % CPU line is indistinguishable from a real idle host."""
    agent = factories.agent(status="active")
    factories.agent_host_sample(agent, collected_at=utcnow() - timedelta(minutes=1))

    resp = await client.get(f"/api/v1/agents/{agent.id}/telemetry/history", headers=viewer_headers)

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 1
    assert points[0]["sample_count"] == 1
    assert all(value is None for value in points[0]["summary"].values())
