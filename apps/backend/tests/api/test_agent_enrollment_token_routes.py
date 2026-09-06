"""Slice B: minting, listing and revoking enrollment tokens over the API.

Design: `docs/design/2026-09-05-agent-reachability-design.md` §4.
"""

from __future__ import annotations

import pytest

ENDPOINT = {"id": "pub1", "label": "Public", "url": "https://cb.example.com"}
MINT_BODY = {"label": "warehouse", "endpoint_id": "pub1", "ttl_seconds": 3600, "max_uses": 1}


@pytest.fixture
def configured_endpoint(db_session):
    from app.schemas.settings import AppSettingsUpdate
    from app.services import settings_service

    settings_service.update_settings(db_session, AppSettingsUpdate(agent_endpoints=[ENDPOINT]))
    db_session.commit()
    return ENDPOINT


@pytest.mark.asyncio
async def test_minting_returns_the_plaintext_exactly_once(
    client, auth_headers, configured_endpoint
):
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens", json=MINT_BODY, headers=auth_headers
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"].startswith("cbe_")
    assert body["endpoint_url"] == "https://cb.example.com"

    listed = await client.get("/api/v1/agents/enrollment-tokens", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(t for t in listed.json() if t["id"] == body["id"])
    assert "token" not in row, "the plaintext must never be readable again"


@pytest.mark.asyncio
async def test_an_unknown_endpoint_is_refused_rather_than_defaulted(
    client, auth_headers, configured_endpoint
):
    """A token scoped to an address nobody declared would send its agents
    somewhere the operator never chose — the defect endpoints exist to remove."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={**MINT_BODY, "endpoint_id": "nope"},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides", [{"ttl_seconds": 0}, {"ttl_seconds": 86401}, {"max_uses": 0}, {"label": ""}]
)
async def test_bounds_are_enforced_at_the_edge(
    client, auth_headers, configured_endpoint, overrides
):
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens", json={**MINT_BODY, **overrides}, headers=auth_headers
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_the_default_ttl_and_max_uses_are_the_safe_ones(
    client, auth_headers, configured_endpoint
):
    """Omitting both must not widen a token: one use, one hour (design §5)."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={"label": "defaults", "endpoint_id": "pub1"},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["max_uses"] == 1


@pytest.mark.asyncio
async def test_revoking_is_reflected_in_the_listing(client, auth_headers, configured_endpoint):
    minted = await client.post(
        "/api/v1/agents/enrollment-tokens", json=MINT_BODY, headers=auth_headers
    )
    token_id = minted.json()["id"]

    resp = await client.post(
        f"/api/v1/agents/enrollment-tokens/{token_id}/revoke", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoking_an_unknown_token_is_404(client, auth_headers):
    resp = await client.post("/api/v1/agents/enrollment-tokens/999999/revoke", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_listing_counts_the_agents_each_token_enrolled(
    client, auth_headers, db_session, factories, configured_endpoint
):
    """Provenance is the reason a revoked token is kept rather than deleted."""
    minted = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={**MINT_BODY, "max_uses": 5},
        headers=auth_headers,
    )
    token_id = minted.json()["id"]
    agent = factories.agent(status="active")
    agent.enrollment_token_id = token_id
    db_session.commit()

    listed = await client.get("/api/v1/agents/enrollment-tokens", headers=auth_headers)
    row = next(t for t in listed.json() if t["id"] == token_id)

    assert row["agent_count"] == 1


@pytest.mark.asyncio
async def test_the_token_route_is_not_parsed_as_an_agent_id(
    client, auth_headers, configured_endpoint
):
    """`/{agent_id}` is declared in this same router. If these literal paths
    were registered after it, "enrollment-tokens" would be parsed as an id and
    this would 422 on the path parameter instead of minting."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens", json=MINT_BODY, headers=auth_headers
    )

    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_minting_is_audited_without_recording_the_token(
    client, auth_headers, db_session, configured_endpoint
):
    """Somebody authorised a credential that can enroll machines. That is worth
    a chained audit row — but the row must not be a copy of the credential."""
    from app.db.models import Log

    resp = await client.post(
        "/api/v1/agents/enrollment-tokens", json=MINT_BODY, headers=auth_headers
    )
    plaintext = resp.json()["token"]

    db_session.expire_all()
    entries = db_session.query(Log).filter(Log.action == "agent_enrollment_token_minted").all()
    assert entries, "a mint must be audited"
    assert all(plaintext not in (repr(e.__dict__)) for e in entries)


@pytest.mark.asyncio
async def test_revoking_is_audited(client, auth_headers, db_session, configured_endpoint):
    from app.db.models import Log

    minted = await client.post(
        "/api/v1/agents/enrollment-tokens", json=MINT_BODY, headers=auth_headers
    )
    await client.post(
        f"/api/v1/agents/enrollment-tokens/{minted.json()['id']}/revoke", headers=auth_headers
    )

    db_session.expire_all()
    assert db_session.query(Log).filter(Log.action == "agent_enrollment_token_revoked").all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/agents/enrollment-tokens"),
        ("get", "/api/v1/agents/enrollment-tokens"),
        ("post", "/api/v1/agents/enrollment-tokens/1/revoke"),
    ],
)
async def test_every_token_route_requires_admin(client, viewer_headers, method, path):
    """A viewer who could mint one could enroll anything."""
    kwargs = {"headers": viewer_headers}
    if method == "post":
        kwargs["json"] = MINT_BODY
    resp = await getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_an_unknown_capability_is_refused_at_mint_not_at_enrollment(
    client, auth_headers, configured_endpoint
):
    """Enrollment is the moment nobody is watching. A token naming a capability
    that does not exist would mint cleanly and then fail every unattended boot
    it was made for, long after the operator walked away."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={**MINT_BODY, "capabilities": {"not_a_capability": True}},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert "not_a_capability" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_capability_object_survives_the_round_trip_as_json(
    client, auth_headers, configured_endpoint
):
    """The scope is persisted in the shape approve_agent already accepts, so a
    token can carry config and not just an on/off flag."""
    resp = await client.post(
        "/api/v1/agents/enrollment-tokens",
        json={
            **MINT_BODY,
            "capabilities": {"host_telemetry": {"enabled": True, "config": {}}},
        },
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["capabilities"]["host_telemetry"]["enabled"] is True
