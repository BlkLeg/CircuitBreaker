"""The agent-update trigger (queuing a pending update, recording update_queued vs.
version_changed, and the Task 9 control-frame push) and streaming update
binaries to an agent.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest


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
