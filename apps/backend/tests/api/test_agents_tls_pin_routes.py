"""Slice 4.1: admin surface for the TLS trust rotation."""

import pytest


@pytest.mark.asyncio
async def test_status_reports_inactive_before_any_rotation(client, auth_headers):
    resp = await client.get("/api/v1/agents/tls-pin/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["successor_mode"] is None


@pytest.mark.asyncio
async def test_rotate_starts_a_rotation(client, auth_headers, self_signed_certificate):
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["active"] is True
    assert body["successor_mode"] == "self_signed"
    assert body["successor_pin_fingerprint"]


@pytest.mark.asyncio
async def test_rotate_never_returns_the_raw_pin(client, auth_headers, self_signed_certificate):
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )
    assert "successor_pin" not in resp.json()


@pytest.mark.asyncio
async def test_second_rotate_is_409(client, auth_headers, self_signed_certificate):
    await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_rotate_unknown_certificate_is_404(client, auth_headers):
    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": 999999},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pending_lists_unconverged_agents(
    client, auth_headers, db_session, factories, self_signed_certificate
):
    from app.services import agent_registry

    converged = factories.agent(status="active", hostname="converged")
    lagging = factories.agent(status="active", hostname="lagging")
    db_session.commit()

    resp = await client.post(
        "/api/v1/agents/tls-pin/rotate",
        json={"certificate_id": self_signed_certificate.id},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    agent_registry.record_tls_pin(db_session, converged, "successor")
    agent_registry.record_tls_pin(db_session, lagging, "current")
    db_session.commit()

    resp = await client.get("/api/v1/agents/tls-pin/pending", headers=auth_headers)
    assert resp.status_code == 200
    hostnames = {row["hostname"] for row in resp.json()}
    assert hostnames == {"lagging"}
    assert [row["bucket"] for row in resp.json()] == ["current"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/agents/tls-pin/status", "/api/v1/agents/tls-pin/pending"]
)
async def test_routes_require_admin(client, viewer_headers, path):
    assert (await client.get(path, headers=viewer_headers)).status_code == 403
