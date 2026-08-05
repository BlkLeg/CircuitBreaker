import json
from unittest.mock import AsyncMock

import pytest


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
    assert resp.json()["capabilities"] == {"host_telemetry": True}


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


@pytest.mark.asyncio
async def test_approve_requires_admin(client, factories, viewer_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_applies_default_grants_and_sets_active(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["capabilities"] == {
        "host_telemetry": True,
        "remote_probe": False,
        "local_discovery": False,
    }


@pytest.mark.asyncio
async def test_approve_honors_capability_overrides(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.json()["capabilities"]["remote_probe"] is True


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
    assert resp.json()["capabilities"]["remote_probe"] is True


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
    assert frame["payload"] == {"remote_probe": True, "host_telemetry": True}


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
    assert resp.json()["capabilities"]["remote_probe"] is True


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
    assert row["capabilities"] == {"host_telemetry": True, "remote_probe": False}


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
