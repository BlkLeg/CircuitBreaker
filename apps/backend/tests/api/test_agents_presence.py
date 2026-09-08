"""The bulk presence REST endpoint (Task 12): online/offline state read from
Redis, capability-grant rendering (including legacy shapes and the contract
shared with agent-detail), linked-hardware summaries, and the single-
mget/single-query contracts a large fleet depends on.

Split out of the former tests/api/test_agents_api.py.
"""

import json
from unittest.mock import AsyncMock

import pytest

from tests.api.agent_fakes import REMOTE_PROBE_DEFAULT_CONFIG, _capture_sql

# The registry default (`CAPABILITY_DEFINITIONS["host_telemetry"]`), spelled out
# so a silent change to the server-side default fails this module's tests loudly.
HOST_TELEMETRY_DEFAULT_CONFIG = {
    "interval_s": 30,
    "include_filesystems": True,
    "include_disks": True,
    "include_network": True,
    "include_temperatures": True,
    "include_virtual": False,
    "include_docker": False,
}


def _redis_with_presence(presence_by_key: dict[str, dict]):
    """Fake Redis client whose `mget` resolves each key against
    `presence_by_key` (agent:presence:{id} -> payload dict), independent of
    the order the caller passes keys in — the bulk endpoint queries the DB
    for its agent id order, which isn't test-controlled."""
    redis_client = AsyncMock()

    async def fake_mget(keys):
        return [json.dumps(presence_by_key[k]) if k in presence_by_key else None for k in keys]

    redis_client.mget.side_effect = fake_mget
    return redis_client


# ── Task 12: bulk presence REST endpoint ────────────────────────────────────


@pytest.mark.asyncio
async def test_presence_requires_viewer_auth(client):
    resp = await client.get("/api/v1/agents/presence")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_presence_returns_whole_fleet_by_default(client, factories, viewer_headers):
    agent_a = factories.agent(status="active", hostname="box1")
    agent_b = factories.agent(status="pending", hostname="box2")

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    ids = {row["agent_id"] for row in resp.json()}
    assert ids == {agent_a.id, agent_b.id}


@pytest.mark.asyncio
async def test_presence_filters_by_explicit_id_list(client, factories, viewer_headers):
    agent_a = factories.agent(status="active")
    factories.agent(status="active")  # not requested — must be excluded

    resp = await client.get(
        "/api/v1/agents/presence", params={"ids": [agent_a.id]}, headers=viewer_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [row["agent_id"] for row in body] == [agent_a.id]


@pytest.mark.asyncio
async def test_presence_reports_online_true_with_connected_since_from_redis(
    client, factories, viewer_headers, monkeypatch
):
    agent = factories.agent(status="active")
    connected_at = "2026-08-04T10:00:00+00:00"
    redis_client = _redis_with_presence(
        {f"agent:presence:{agent.id}": {"connected_at": connected_at, "worker": "w1"}}
    )
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["online"] is True
    from datetime import datetime

    assert datetime.fromisoformat(row["connected_since"]) == datetime.fromisoformat(connected_at)


@pytest.mark.asyncio
async def test_presence_reports_offline_when_presence_key_ttl_expired(
    client, factories, viewer_headers, monkeypatch
):
    agent = factories.agent(status="active")
    # No entry for this agent's presence key at all — same as having expired.
    redis_client = _redis_with_presence({})
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["online"] is False
    assert row["connected_since"] is None


@pytest.mark.asyncio
async def test_presence_reflects_last_seen_at_from_db(
    client, factories, viewer_headers, monkeypatch
):
    from app.core.time import utcnow

    last_seen = utcnow()
    agent = factories.agent(status="active", last_seen_at=last_seen)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["last_seen_at"] is not None


@pytest.mark.asyncio
async def test_presence_includes_capability_grants(client, factories, viewer_headers, monkeypatch):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    # Task 15 / D-11: presence emits the canonical {enabled, config} shape
    # unconditionally — never a bare boolean, and with no compatibility flag.
    assert row["capabilities"] == {
        "host_telemetry": {"enabled": True, "config": HOST_TELEMETRY_DEFAULT_CONFIG},
        "remote_probe": {"enabled": False, "config": REMOTE_PROBE_DEFAULT_CONFIG},
    }


@pytest.mark.asyncio
async def test_presence_and_agent_detail_report_identical_capability_grants(
    client, factories, viewer_headers, monkeypatch
):
    """The contract lock: `/agents/presence` and `/agents/{id}` must project the
    same grant rows into byte-identical JSON, so slice 3 adding probe scope
    config cannot make the two endpoints drift."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent, capability="host_telemetry", enabled=True, config={"interval_s": 90}
    )
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    presence = await client.get("/api/v1/agents/presence", headers=viewer_headers)
    detail = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)

    assert presence.status_code == 200
    assert detail.status_code == 200
    row = next(r for r in presence.json() if r["agent_id"] == agent.id)
    assert row["capabilities"] == detail.json()["capabilities"]
    assert row["capabilities"]["host_telemetry"]["config"]["interval_s"] == 90


@pytest.mark.asyncio
async def test_unknown_legacy_capability_row_is_returned_verbatim_not_500(
    client, factories, viewer_headers, monkeypatch
):
    """A grant row naming a capability this build no longer declares must
    render, not 500 the whole fleet. `approve_agent` wrote rows for arbitrary
    keys before Task 14's 422 validator, and no migration cleans them up."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent, capability="legacy_thing", enabled=True, config={"whatever": 1}
    )
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    presence = await client.get("/api/v1/agents/presence", headers=viewer_headers)
    detail = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)

    assert presence.status_code == 200
    assert detail.status_code == 200
    expected = {"enabled": True, "config": {"whatever": 1}}
    row = next(r for r in presence.json() if r["agent_id"] == agent.id)
    assert row["capabilities"]["legacy_thing"] == expected
    assert detail.json()["capabilities"]["legacy_thing"] == expected


@pytest.mark.asyncio
async def test_approve_and_capabilities_put_still_accept_legacy_boolean_input(
    client, factories, auth_headers
):
    """D-11: every REST *request* keeps accepting `bool | CapabilityGrant` per
    capability indefinitely — only responses are canonicalized."""
    agent = factories.agent(status="pending")

    approve = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"host_telemetry": True, "remote_probe": False}},
        headers=auth_headers,
    )
    assert approve.status_code == 200
    assert approve.json()["capabilities"]["host_telemetry"] == {
        "enabled": True,
        "config": HOST_TELEMETRY_DEFAULT_CONFIG,
    }
    assert approve.json()["capabilities"]["remote_probe"] == {
        "enabled": False,
        "config": REMOTE_PROBE_DEFAULT_CONFIG,
    }

    put = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert put.status_code == 200
    assert put.json()["capabilities"]["remote_probe"] == {
        "enabled": True,
        "config": REMOTE_PROBE_DEFAULT_CONFIG,
    }


@pytest.mark.asyncio
async def test_presence_includes_linked_hardware_summary(
    client, factories, viewer_headers, monkeypatch
):
    hw = factories.hardware(
        name="rack-1",
        hostname="rack1.local",
        ip_address="10.0.0.9",
        mac_address="aa:bb:cc:dd:ee:ff",
    )
    agent = factories.agent(status="active", hardware_id=hw.id)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["hardware"] == {
        "id": hw.id,
        "name": "rack-1",
        "hostname": "rack1.local",
        "ip_address": "10.0.0.9",
        "mac_address": "aa:bb:cc:dd:ee:ff",
    }


@pytest.mark.asyncio
async def test_presence_hardware_is_null_when_agent_has_no_linked_hardware(
    client, factories, viewer_headers, monkeypatch
):
    agent = factories.agent(status="active")
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["hardware"] is None


@pytest.mark.asyncio
async def test_presence_issues_single_mget_regardless_of_fleet_size(
    client, factories, viewer_headers, monkeypatch
):
    """Task 12: a bulk endpoint, not N+1 per-agent Redis reads."""
    for _ in range(5):
        factories.agent(status="active")
    redis_client = _redis_with_presence({})
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    assert len(resp.json()) >= 5
    redis_client.mget.assert_called_once()
    redis_client.get.assert_not_called()
    redis_client.exists.assert_not_called()


@pytest.mark.asyncio
async def test_presence_issues_single_query_regardless_of_fleet_size(
    client, factories, viewer_headers, monkeypatch
):
    """Task 15: canonicalizing the grant shape must not reintroduce an N+1 —
    a 20-agent fleet still costs exactly one `agent_capability_grants` SELECT."""
    for _ in range(20):
        agent = factories.agent(status="active")
        factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/agents/presence", headers=viewer_headers)

    assert resp.status_code == 200
    assert len(resp.json()) >= 20
    grant_queries = [
        s
        for s in statements
        if "agent_capability_grants" in s and s.lstrip().upper().startswith("SELECT")
    ]
    assert len(grant_queries) == 1, grant_queries
