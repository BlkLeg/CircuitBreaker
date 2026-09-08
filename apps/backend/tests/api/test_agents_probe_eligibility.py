"""Slice 3 section 7: the assigned-probes list on an agent, and the probe-eligible
agent listing used to pick a probing agent for a new monitor.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

from tests.api.agent_fakes import REMOTE_PROBE_DEFAULT_CONFIG

# ── Slice 3 §7: assigned probes and the eligible-agent listing ───────────────


class _FakePresenceRedis:
    """The two reads `is_agent_online` / `get_agent_connection_owner` make."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)


@pytest.fixture
def probe_presence(monkeypatch):
    """Redis double plus a `mark(agent)` helper. Offline is the default, so a
    test that forgets to bring an agent online fails loudly."""
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakePresenceRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    def mark(agent, worker: str = "worker-1") -> None:
        store[f"agent:presence:{agent.id}"] = "{}"
        store[f"agent:connection:{agent.id}"] = worker

    return mark


def _probe_ready_agent(factories, name: str, **kwargs):
    agent = factories.agent(status="active", name=name, **kwargs)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    return agent


@pytest.mark.asyncio
async def test_agent_probes_lists_assigned_monitors_with_execution_state(
    client, factories, viewer_headers
):
    agent = _probe_ready_agent(factories, "branch-office")
    assigned = factories.monitor_item(
        name="edge icmp",
        host="10.0.0.9",
        check_type="icmp",
        probe_agent_id=agent.id,
        last_status="up",
        probe_execution_status="unavailable",
        probe_execution_reason="agent_offline",
    )
    factories.monitor_item(name="server side")  # unassigned — must not appear
    factories.monitor_probe_run(assigned, agent, status="dispatched")
    factories.session.flush()

    resp = await client.get(f"/api/v1/agents/{agent.id}/probes", headers=viewer_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == agent.id
    # §2's per-agent concurrency, from the grant's registry defaults.
    assert body["max_concurrent"] == REMOTE_PROBE_DEFAULT_CONFIG["max_concurrent"]
    assert body["active_runs"] == 1
    assert [a["monitor_id"] for a in body["assignments"]] == [assigned.id]
    row = body["assignments"][0]
    assert row["name"] == "edge icmp"
    assert row["check_type"] == "icmp"
    assert row["host"] == "10.0.0.9"
    assert row["interval_secs"] == 60
    assert row["status"] == "up"  # target state, not execution condition
    assert row["probe_execution_status"] == "unavailable"
    assert row["probe_execution_reason"] == "agent_offline"
    assert row["probe_last_result_at"] is None

    assert (
        await client.get("/api/v1/agents/999999/probes", headers=viewer_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_agent_probes_reject_scoped_token_without_read(client, factories, db_session):
    """SEC-08: the assigned-probes list is monitor data and carries the read scope.

    A write-only token could once enumerate every monitor's name and host
    through this route, because a role check ignores token scopes.
    """
    from app.core.security import create_salted_api_token_hash
    from app.db.models import APIToken

    agent = _probe_ready_agent(factories, "scope-check")
    factories.monitor_item(name="edge icmp", host="10.0.0.9", probe_agent_id=agent.id)
    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash("sec8-probes-write-only"),
            label="SEC-08 write-only token",
            created_by=owner.id,
            scopes=["write:*"],
        )
    )
    db_session.flush()

    resp = await client.get(
        f"/api/v1/agents/{agent.id}/probes",
        headers={"Authorization": "Bearer sec8-probes-write-only"},
    )

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_eligible_agents_listing_reports_online_grant_readiness_concurrency_and_scope(
    client, factories, viewer_headers, probe_presence
):
    online = _probe_ready_agent(factories, "in-network")
    offline = _probe_ready_agent(factories, "dark")
    ungranted = factories.agent(status="active", name="no-grant")
    factories.agent_network(ungranted)
    probe_presence(online)
    probe_presence(ungranted)

    resp = await client.get(
        "/api/v1/agents/probe-eligible",
        headers=viewer_headers,
        params={"host": "10.0.0.9", "check_type": "icmp"},
    )

    assert resp.status_code == 200, resp.text
    rows = {row["agent_id"]: row for row in resp.json()}

    good = rows[online.id]
    assert good["name"] == "in-network"
    assert good["online"] is True
    assert good["granted"] is True
    assert good["readiness"] == "ready"
    assert good["max_concurrent"] == REMOTE_PROBE_DEFAULT_CONFIG["max_concurrent"]
    assert good["active_runs"] == 0
    assert good["assigned_monitors"] == 0
    assert good["scope_networks"] == ["10.0.0.0/24"]
    assert good["in_scope"] is True
    assert good["eligible"] is True
    assert good["reason"] is None

    assert rows[offline.id]["online"] is False
    assert rows[offline.id]["eligible"] is False
    assert rows[offline.id]["reason"] == "agent_offline"

    assert rows[ungranted.id]["granted"] is False
    assert rows[ungranted.id]["readiness"] is None
    assert rows[ungranted.id]["eligible"] is False
    assert rows[ungranted.id]["reason"] == "capability_disabled"

    # Scope compatibility is answered per destination, not per agent.
    out = await client.get(
        "/api/v1/agents/probe-eligible",
        headers=viewer_headers,
        params={"host": "192.168.50.5", "check_type": "icmp"},
    )
    out_rows = {row["agent_id"]: row for row in out.json()}
    assert out_rows[online.id]["in_scope"] is False
    assert out_rows[online.id]["eligible"] is False
    assert out_rows[online.id]["reason"] == "out_of_scope"


@pytest.mark.asyncio
async def test_eligible_agents_listing_resolves_the_destination_from_a_monitor(
    client, factories, viewer_headers, probe_presence
):
    agent = _probe_ready_agent(factories, "resolver")
    probe_presence(agent)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="icmp")
    factories.session.flush()

    resp = await client.get(
        "/api/v1/agents/probe-eligible",
        headers=viewer_headers,
        params={"monitor_id": monitor.id},
    )

    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["agent_id"] == agent.id)
    assert row["in_scope"] is True
    assert row["eligible"] is True

    # Neither a monitor nor a host leaves scope compatibility unanswerable.
    assert (
        await client.get("/api/v1/agents/probe-eligible", headers=viewer_headers)
    ).status_code == 422


@pytest.mark.asyncio
async def test_probe_eligible_route_wins_over_agent_id(client, viewer_headers):
    """A literal collection path has to be declared above "/{agent_id}", the
    same way "/pending", "/capability-defaults" and "/presence" already are."""
    resp = await client.get(
        "/api/v1/agents/probe-eligible", headers=viewer_headers, params={"host": "10.0.0.9"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
