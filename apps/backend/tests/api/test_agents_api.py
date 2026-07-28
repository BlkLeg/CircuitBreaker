import pytest


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
