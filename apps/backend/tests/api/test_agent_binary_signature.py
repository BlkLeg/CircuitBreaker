"""Slice 4.2: the detached signature is served beside the binary."""

import base64
import os

import pytest


@pytest.fixture
def agent_binaries_dir(tmp_path, monkeypatch):
    """A populated agent-binaries directory. The signature bytes are random
    rather than a real Ed25519 signature: this route serves a file, it does
    not verify one — verification is the agent's job and is tested in Go."""
    from app.services import agent_update

    version_dir = tmp_path / "1.2.3"
    version_dir.mkdir()
    (version_dir / "cb-agent-linux-amd64").write_bytes(b"binary")
    (version_dir / "cb-agent-linux-amd64.sig").write_bytes(base64.b64encode(os.urandom(64)))
    (tmp_path / "manifest.json").write_text(
        '{"1.2.3": {"linux-amd64": "deadbeef", "linux-amd64.sig": "cb-agent-linux-amd64.sig"}}'
    )
    monkeypatch.setattr(agent_update, "AGENT_BINARIES_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_signature_is_served(client, agent_binaries_dir):
    resp = await client.get("/api/v1/agents/binary/1.2.3/linux/amd64.sig")
    assert resp.status_code == 200
    assert resp.content


@pytest.mark.asyncio
async def test_missing_signature_is_404(client, agent_binaries_dir):
    resp = await client.get("/api/v1/agents/binary/1.2.3/linux/arm64.sig")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_signature_route_rejects_path_traversal(client, agent_binaries_dir):
    resp = await client.get("/api/v1/agents/binary/..%2F..%2Fetc/linux/amd64.sig")
    assert resp.status_code in (400, 404)


@pytest.mark.asyncio
async def test_the_signature_route_is_reachable_not_shadowed_by_the_binary_route(
    client, agent_binaries_dir
):
    """Route order regression guard. A `{str}` path param accepts dots, so if
    the binary route is registered first it captures arch="amd64.sig" and this
    handler becomes dead code that appears to work. Distinguished by the
    detail text: the binary route's 404 says "Binary not found", this one
    names the signature."""
    (agent_binaries_dir / "1.2.3" / "cb-agent-linux-arm64").write_bytes(b"binary")

    resp = await client.get("/api/v1/agents/binary/1.2.3/linux/arm64.sig")

    assert resp.status_code == 404
    assert "signature" in resp.json()["detail"].lower()
