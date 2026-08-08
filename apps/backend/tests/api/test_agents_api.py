import contextlib
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

# The registry defaults (`CAPABILITY_DEFINITIONS`), spelled out so a silent
# change to the server-side defaults fails these tests loudly.
HOST_TELEMETRY_DEFAULT_CONFIG = {
    "interval_s": 30,
    "include_filesystems": True,
    "include_disks": True,
    "include_network": True,
    "include_temperatures": True,
    "include_virtual": False,
    "include_docker": False,
}

REMOTE_PROBE_DEFAULT_CONFIG = {
    "max_concurrent": 20,
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "additional_hostnames": [],
}

# The registry default (`CAPABILITY_DEFINITIONS["local_discovery"]`), spelled out
# for the same reason: a silent change to the server-side defaults must fail
# loudly here rather than quietly ship a wider scan to every approved agent.
LOCAL_DISCOVERY_DEFAULT_CONFIG = {
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "max_addresses_per_job": 1024,
    "max_concurrent_hosts": 64,
    "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    "host_timeout_ms": 1500,
    "job_timeout_seconds": 300,
    "auto_discovery_paused": False,
}


@contextlib.contextmanager
def _capture_sql():
    """Record every statement the engine executes while the block is open."""
    from app.db.session import engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", _record)


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


@pytest.mark.asyncio
async def test_list_agents_requires_viewer_auth(client):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_agents_returns_summaries(client, factories, viewer_headers):
    factories.agent(status="active", hostname="box1")
    factories.agent(status="pending", hostname="box2")

    resp = await client.get("/api/v1/agents", headers=viewer_headers)
    assert resp.status_code == 200
    hostnames = {a["hostname"] for a in resp.json()}
    assert hostnames == {"box1", "box2"}


@pytest.mark.asyncio
async def test_pending_endpoint_only_returns_pending(client, factories, viewer_headers):
    factories.agent(status="active", hostname="active-one")
    pending = factories.agent(status="pending", hostname="pending-one")

    resp = await client.get("/api/v1/agents/pending", headers=viewer_headers)
    assert resp.status_code == 200
    ids = [a["id"] for a in resp.json()]
    assert ids == [pending.id]


@pytest.mark.asyncio
async def test_get_agent_detail_includes_capabilities(client, factories, viewer_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["capabilities"] == {
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        }
    }


@pytest.mark.asyncio
async def test_get_agent_detail_includes_hardware_proposal(client, factories, viewer_headers):
    from app.db.models import Hardware

    hw = Hardware(name="matched-box", machine_id_hash="mid-hash-1")
    factories.session.add(hw)
    factories.session.flush()

    agent = factories.agent(status="pending", machine_id_hash="mid-hash-1")

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposed_hardware_id"] == hw.id
    assert body["proposed_hardware_name"] == "matched-box"
    assert body["duplicate_machine_id"] is False


@pytest.mark.asyncio
async def test_agent_detail_and_pairing_lookup_report_identical_duplicate_warning(
    client, factories, auth_headers
):
    """Two agents sharing a machine_id_hash (e.g. a cloned VM image) must be
    flagged identically by both the agent-detail endpoint and the
    pairing-lookup endpoint — an operator reviewing from either screen sees
    the same warning."""
    from unittest.mock import AsyncMock

    factories.agent(status="active", machine_id_hash="dup-hash")
    pending = factories.agent(status="pending", machine_id_hash="dup-hash", hostname="pending-box")

    detail_resp = await client.get(f"/api/v1/agents/{pending.id}", headers=auth_headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["duplicate_machine_id"] is True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.agent_enrollment.consume_pairing_code",
            AsyncMock(return_value=pending.id),
        )
        lookup_resp = await client.post(
            "/api/v1/agents/pairing/lookup",
            json={"code": "ABCD-EFGH-JKMN"},
            headers=auth_headers,
        )
    assert lookup_resp.status_code == 200
    assert lookup_resp.json()["duplicate_machine_id"] is True
    assert lookup_resp.json()["duplicate_machine_id"] == detail_resp.json()["duplicate_machine_id"]


@pytest.mark.asyncio
async def test_patch_requires_editor_not_viewer(client, factories, viewer_headers):
    agent = factories.agent()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=viewer_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_renames_agent(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


# ── Task 19: host-link editing after approval ──────────────────────────────


@pytest.mark.asyncio
async def test_patch_requires_editor_not_viewer_for_hardware_link(
    client, factories, viewer_headers
):
    agent = factories.agent(status="active")
    hardware = factories.hardware()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_relinks_approved_agent_to_different_hardware(client, factories, auth_headers):
    original = factories.hardware()
    replacement = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": replacement.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == replacement.id

    detail_resp = await client.get(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert detail_resp.json()["hardware_id"] == replacement.id


@pytest.mark.asyncio
async def test_patch_relink_records_host_link_changed_event(client, factories, auth_headers):
    original = factories.hardware()
    replacement = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": replacement.id},
        headers=auth_headers,
    )

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {
        "previous_hardware_id": original.id,
        "hardware_id": replacement.id,
    }


@pytest.mark.asyncio
async def test_patch_unlinks_approved_agent_hardware(client, factories, auth_headers):
    original = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] is None

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {"previous_hardware_id": original.id, "hardware_id": None}


@pytest.mark.asyncio
async def test_patch_links_previously_unlinked_agent(client, factories, auth_headers):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=None)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == hardware.id

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {"previous_hardware_id": None, "hardware_id": hardware.id}


@pytest.mark.asyncio
async def test_patch_hardware_id_unchanged_records_no_event(client, factories, auth_headers):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    types = [e["event_type"] for e in events_resp.json()]
    assert "host_link_changed" not in types


@pytest.mark.asyncio
async def test_patch_rejects_unknown_hardware_id(client, factories, auth_headers):
    agent = factories.agent(status="active")
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": 999999999},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.patch("/api/v1/agents/999999999", json={"name": "x"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_requires_admin(client, factories, viewer_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_with_omitted_capabilities_grants_the_full_normal_preset(
    client, factories, auth_headers
):
    """Task 14 / D-10: an approve body with no `capabilities` grants all three
    capabilities enabled, each carrying the server registry's default config."""
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["capabilities"] == {
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        },
        "remote_probe": {"enabled": True, "config": REMOTE_PROBE_DEFAULT_CONFIG},
        "local_discovery": {"enabled": True, "config": LOCAL_DISCOVERY_DEFAULT_CONFIG},
    }


@pytest.mark.asyncio
async def test_approve_rejects_invalid_host_telemetry_config_with_422(
    client, factories, auth_headers
):
    """Task 14: `ApproveRequest` validates capability config the same way
    `CapabilitiesUpdateRequest` does, so a bad cadence is a 422 — not the 500
    the un-validated approve body used to produce via a bare `ValueError`."""
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"host_telemetry": {"enabled": True, "config": {"interval_s": 5}}}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approve_rejects_unknown_capability_name(client, factories, auth_headers):
    """Task 14: the registry is the closed set of capability names; approving
    with anything else is a 422, not a grant row for an arbitrary string."""
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"not_a_capability": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_capabilities_update_rejects_malformed_remote_probe_scope_with_422(
    client, factories, auth_headers
):
    """Slice 3 Task 5: a scope field of the wrong *type* is administrator error,
    so it has to surface as a 422 like every other bad config. Only `ValueError`
    reaches `_validate_capability_map`'s handler — a `TypeError` raised while
    iterating a non-list would escape as a 500 from an admin route instead."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True, config={})

    for config in ({"additional_cidrs": 5}, {"excluded_cidrs": None}, {"scope_mode": []}):
        resp = await client.put(
            f"/api/v1/agents/{agent.id}/capabilities",
            json={"capabilities": {"remote_probe": {"enabled": True, "config": config}}},
            headers=auth_headers,
        )
        assert resp.status_code == 422, config


@pytest.mark.asyncio
async def test_capability_defaults_endpoint_matches_what_an_omitted_approve_grants(
    client, factories, auth_headers
):
    """Structural lock (Task 14): the frontend's approval preset is fetched from
    this endpoint, so it can never drift from what the server actually grants."""
    defaults = await client.get("/api/v1/agents/capability-defaults", headers=auth_headers)
    assert defaults.status_code == 200

    agent = factories.agent(status="pending")
    approve = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert approve.status_code == 200
    assert approve.json()["capabilities"] == defaults.json()


@pytest.mark.asyncio
async def test_capability_defaults_is_readable_by_a_viewer(client, viewer_headers):
    """Declared above "/{agent_id}" so "capability-defaults" is never parsed as
    an agent id (which would 422 on the int path param for a viewer)."""
    resp = await client.get("/api/v1/agents/capability-defaults", headers=viewer_headers)
    assert resp.status_code == 200
    assert set(resp.json()) == {"host_telemetry", "remote_probe", "local_discovery"}


@pytest.mark.asyncio
async def test_approve_honors_capability_overrides(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_approve_accepts_hardware_id_and_host_link_action(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    hardware = factories.hardware()
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"hardware_id": hardware.id, "host_link_action": "accept"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == hardware.id


@pytest.mark.asyncio
async def test_approve_records_host_link_action_on_approved_event(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    hardware = factories.hardware()
    await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"hardware_id": hardware.id, "host_link_action": "create"},
        headers=auth_headers,
    )

    resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    approved = next(e for e in resp.json() if e["event_type"] == "approved")
    assert approved["detail"] == {"hardware_id": hardware.id, "host_link_action": "create"}


@pytest.mark.asyncio
async def test_approve_rejects_unknown_host_link_action(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"host_link_action": "bogus"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approve_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999999/approve", json={}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_sets_rejected_status(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/reject", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999999/reject", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_records_reason(client, factories, auth_headers):
    agent = factories.agent(status="active")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        json={"reason": "lost device"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post(
        "/api/v1/agents/999999999/revoke", json={"reason": "n/a"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_capabilities_put_updates_grants(client, factories, auth_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_capabilities_put_publishes_control_frame_for_immediate_delivery(
    client, factories, auth_headers, monkeypatch
):
    """Task 9: put_capabilities also pushes the change through
    agent_registry.publish_agent_control_frame — the cross-worker delivery
    primitive Task 8 added — on top of the DB write, so a connected agent
    picks it up immediately regardless of which worker holds its /link
    socket. See test_ws_agents_link.py's
    test_link_delivers_capabilities_set_published_by_another_worker for the
    matching end-to-end proof that a published frame actually reaches the
    socket; this test only pins the call site's payload."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    publish = AsyncMock(return_value=True)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", publish)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    publish.assert_called_once()
    published_agent_id, frame = publish.call_args[0]
    assert published_agent_id == agent.id
    assert frame["type"] == "capabilities.set"
    # The full, authoritative grants set — not just the one capability this
    # request changed — same as the connect-time capabilities.set send.
    assert frame["payload"] == {
        "remote_probe": {"enabled": True, "config": REMOTE_PROBE_DEFAULT_CONFIG},
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        },
    }


@pytest.mark.asyncio
async def test_capabilities_put_succeeds_even_when_control_frame_publish_fails(
    client, factories, auth_headers, monkeypatch
):
    """publish_agent_control_frame never raises (see its docstring), but this
    pins the caller-side contract too: a degraded/unavailable Redis must not
    fail the request or leave the DB write unapplied — the agent still picks
    the change up on its own next reconnect/poll."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    monkeypatch.setattr(
        agent_registry, "publish_agent_control_frame", AsyncMock(return_value=False)
    )

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_delete_requires_admin(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_requires_admin_not_viewer(client, factories, viewer_headers):
    agent = factories.agent()
    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_deleting_an_agent_with_assigned_monitors_returns_409(
    client, factories, auth_headers
):
    """`monitor_items.probe_agent_id` is RESTRICT (Task 6), so without this
    pre-check the delete surfaces as an unhandled IntegrityError and a 500.
    §8: agent deletion is blocked while assignments remain — unassigning is a
    decision the operator makes explicitly, never a side effect of a delete."""
    from app.db.models import Agent

    agent = factories.agent(status="active")
    factories.monitor_item(probe_agent_id=agent.id)

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]
    assert factories.session.get(Agent, agent.id) is not None


@pytest.mark.asyncio
async def test_delete_succeeds_after_the_monitors_are_reassigned(client, factories, auth_headers):
    agent = factories.agent(status="active")
    other = factories.agent(status="active")
    monitor = factories.monitor_item(probe_agent_id=agent.id)

    blocked = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert blocked.status_code == 409

    monitor.probe_agent_id = other.id
    factories.session.flush()

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_events_endpoint_lists_history(client, factories, viewer_headers):
    agent = factories.agent()
    factories.agent_event(agent, event_type="enrolled")
    factories.agent_event(agent, event_type="approved")

    resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=viewer_headers)
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()]
    assert types == ["approved", "enrolled"]  # newest first


@pytest.mark.asyncio
async def test_events_endpoint_returns_404_for_unknown_agent(client, viewer_headers):
    resp = await client.get("/api/v1/agents/999999999/events", headers=viewer_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pairing_lookup_resolves_pending_agent(client, factories, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="pending", hostname="box1")
    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=agent.id)
    )

    resp = await client.post(
        "/api/v1/agents/pairing/lookup",
        json={"code": "ABCD-EFGH-JKMN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent.id


@pytest.mark.asyncio
async def test_pairing_lookup_records_miss_on_unknown_code(client, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=None)
    )
    miss = AsyncMock()
    monkeypatch.setattr("app.services.agent_enrollment.record_pairing_miss", miss)

    resp = await client.post(
        "/api/v1/agents/pairing/lookup",
        json={"code": "ZZZZ-ZZZZ-ZZZZ"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    miss.assert_called_once()


@pytest.mark.asyncio
async def test_update_requires_admin(client, factories, viewer_headers):
    agent = factories.agent(status="active")
    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999999/update", json={}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_returns_400_when_no_binaries_available(
    client,
    factories,
    auth_headers,
    monkeypatch,
    tmp_path,
):
    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path / "nonexistent")
    agent = factories.agent(status="active")

    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_returns_404_when_no_binary_for_platform(
    client,
    factories,
    auth_headers,
    monkeypatch,
    tmp_path,
):
    import json

    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"0.2.0": {"windows-arm64": "abc123"}}))
    agent = factories.agent(status="active", os="linux", arch="amd64")

    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_queues_pending_update_at_latest_version(
    client, factories, auth_headers, monkeypatch, tmp_path
):
    import json
    from unittest.mock import AsyncMock

    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"0.2.0": {"linux-amd64": "abc123"}}))
    agent = factories.agent(status="active", os="linux", arch="amd64")

    request_update = AsyncMock()
    monkeypatch.setattr(agent_update, "request_update", request_update)

    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "version": "0.2.0"}
    request_update.assert_called_once_with(
        agent.id,
        version="0.2.0",
        sha256="abc123",
        arch="amd64",
        os_name="linux",
    )


@pytest.mark.asyncio
async def test_update_records_update_queued_not_version_changed(
    client, factories, auth_headers, monkeypatch, tmp_path
):
    """Task 24: queue-time only ever records `update_queued` — `version_changed`
    must not appear until a later reconnect actually reports the target
    version (see test_ws_agents_link.py's
    test_link_reconnect_at_target_version_records_version_changed for that
    half). Also asserts the row's `pending_update_version` is set to the
    version just queued, since that's what a later hello/update.status
    compares against."""
    import json
    from unittest.mock import AsyncMock

    from app.services import agent_registry, agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"0.2.0": {"linux-amd64": "abc123"}}))
    agent = factories.agent(status="active", os="linux", arch="amd64", agent_version="0.1.0")

    monkeypatch.setattr(agent_update, "request_update", AsyncMock())
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(return_value=True))

    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=auth_headers)
    assert resp.status_code == 200

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    types = [e["event_type"] for e in events_resp.json()]
    assert "update_queued" in types
    assert "version_changed" not in types

    detail_resp = await client.get(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert detail_resp.json()["agent_version"] == "0.1.0"  # untouched at request time


@pytest.mark.asyncio
async def test_update_publishes_control_frame_for_immediate_delivery(
    client, factories, auth_headers, monkeypatch, tmp_path
):
    """Task 9: post_update also pushes the update trigger through
    agent_registry.publish_agent_control_frame, on top of the existing
    Redis-queued pending update (agent_update.request_update, left
    untouched above) that link_stream's poll fallback still consumes if this
    publish is missed or delivered to no listener."""
    import json
    from unittest.mock import AsyncMock

    from app.services import agent_registry, agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"0.2.0": {"linux-amd64": "abc123"}}))
    agent = factories.agent(status="active", os="linux", arch="amd64")

    monkeypatch.setattr(agent_update, "request_update", AsyncMock())
    publish = AsyncMock(return_value=True)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", publish)

    resp = await client.post(f"/api/v1/agents/{agent.id}/update", json={}, headers=auth_headers)
    assert resp.status_code == 200

    publish.assert_called_once()
    published_agent_id, frame = publish.call_args[0]
    assert published_agent_id == agent.id
    assert frame["type"] == "update"
    assert frame["payload"] == {
        "version": "0.2.0",
        "sha256": "abc123",
        "arch": "amd64",
        "os": "linux",
    }


@pytest.mark.asyncio
async def test_get_binary_streams_file_unauthenticated(client, tmp_path, monkeypatch):
    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    version_dir = tmp_path / "0.2.0"
    version_dir.mkdir()
    (version_dir / "cb-agent-linux-amd64").write_bytes(b"fake binary contents")

    resp = await client.get("/api/v1/agents/binary/0.2.0/linux/amd64")
    assert resp.status_code == 200
    assert resp.content == b"fake binary contents"


@pytest.mark.asyncio
async def test_get_binary_404s_for_missing_file(client, tmp_path, monkeypatch):
    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)

    resp = await client.get("/api/v1/agents/binary/9.9.9/linux/amd64")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_binary_rejects_path_traversal(client, tmp_path, monkeypatch):
    from app.services import agent_update

    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)

    resp = await client.get("/api/v1/agents/binary/..%2F..%2Fetc/linux/passwd")
    assert resp.status_code == 404


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


# ── server-key rotation admin endpoints (Task 28) ──────────────────────────


@pytest.mark.asyncio
async def test_server_key_status_requires_admin_not_viewer(client, viewer_headers):
    resp = await client.get("/api/v1/agents/server-key/status", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_server_key_rotate_requires_admin_not_viewer(client, viewer_headers):
    resp = await client.post("/api/v1/agents/server-key/rotate", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_server_key_status_reports_inactive_with_no_rotation(client, auth_headers):
    resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["successor_key_fingerprint"] is None
    assert body["started_at"] is None
    assert body["overlap_expires_at"] is None
    assert len(body["current_key_fingerprint"]) == 32


@pytest.mark.asyncio
async def test_server_key_rotate_starts_rotation_and_status_reflects_it(client, auth_headers):
    status_before = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    current_fingerprint = status_before.json()["current_key_fingerprint"]

    rotate_resp = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)

    assert rotate_resp.status_code == 201
    body = rotate_resp.json()
    assert body["active"] is True
    assert body["current_key_fingerprint"] == current_fingerprint
    assert body["successor_key_fingerprint"] is not None
    assert body["successor_key_fingerprint"] != current_fingerprint
    assert body["started_at"] is not None
    assert body["overlap_expires_at"] is not None

    status_after = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert status_after.json() == body


@pytest.mark.asyncio
async def test_server_key_rotate_rejects_second_call_while_overlap_active(client, auth_headers):
    first = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)

    assert second.status_code == 409
    # The first rotation's successor is untouched by the rejected attempt.
    status = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert status.json()["successor_key_fingerprint"] == first.json()["successor_key_fingerprint"]


@pytest.mark.asyncio
async def test_get_agent_detail_exposes_spool_state(client, factories, viewer_headers):
    """`AgentRead` carries the reported spool backlog (Task 16, D-12). NULL
    means "never reported" — an agent predating `HeartbeatPayload` — and must
    survive serialization as null rather than being coerced to 0."""
    from app.core.time import utcnow

    never_reported = factories.agent(status="active")
    reporting = factories.agent(status="active")
    reporting.spool_depth = 12
    reporting.spool_bytes = 4096
    reporting.spool_reported_at = utcnow()
    factories.session.commit()

    resp = await client.get(f"/api/v1/agents/{reporting.id}", headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["spool_depth"] == 12
    assert body["spool_bytes"] == 4096
    assert body["spool_reported_at"] is not None

    resp = await client.get(f"/api/v1/agents/{never_reported.id}", headers=viewer_headers)
    body = resp.json()
    assert body["spool_depth"] is None
    assert body["spool_bytes"] is None
    assert body["spool_reported_at"] is None


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
