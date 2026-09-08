"""Server-key rotation admin endpoints (Task 28, INC-13): starting a rotation,
status reporting, fleet-adoption bucketing by which key an agent last pinned,
and the pending-agents listing.

Split out of the former tests/api/test_agents_api.py.
"""

import json

import pytest

from tests.api.agent_fakes import _capture_sql

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


# ── server-key rotation: fleet adoption (INC-13) ──────────────────────────────


@pytest.mark.asyncio
async def test_rotation_status_omits_fleet_when_no_rotation_active(client, auth_headers):
    resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["fleet"] is None


@pytest.mark.asyncio
async def test_rotation_status_buckets_the_fleet_by_key_last_handshaked(
    client, auth_headers, factories, db_session
):
    """The three buckets the panel shows, and the boundary that separates them.

    `started_at` is the divider: a pin recorded BEFORE this rotation began says
    nothing about this rotation, so such an agent is `unseen`, not `current`.
    """
    from datetime import timedelta

    from app.core.time import utcnow

    on_successor = factories.agent(status="active")
    on_current = factories.agent(status="active")
    factories.agent(status="active")  # never_seen — no pin, counts as unseen
    stale_pin = factories.agent(status="active")
    revoked = factories.agent(status="revoked")

    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201
    started_at = utcnow()

    on_successor.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    on_current.server_pk_current_pinned_at = started_at + timedelta(minutes=1)
    # Pinned long before this rotation started — tells us nothing about it.
    stale_pin.server_pk_current_pinned_at = started_at - timedelta(days=30)
    revoked.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    db_session.flush()

    resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)
    assert resp.status_code == 200
    fleet = resp.json()["fleet"]

    assert fleet["successor"] == 1
    assert fleet["current"] == 1
    assert fleet["unseen"] == 2, "never-handshaked and stale-pin both count as unseen"
    assert fleet["total"] == 4, "revoked agents are excluded from every bucket"


@pytest.mark.asyncio
async def test_rotation_status_adoption_is_one_query_regardless_of_fleet_size(
    client, auth_headers, factories
):
    """Same contract as test_presence_issues_single_query_regardless_of_fleet_size:
    the panel must not cost one query per agent. See _latest_samples' docstring
    at api/agents.py:284 for why this is pinned rather than merely intended."""
    for _ in range(20):
        factories.agent(status="active")

    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/agents/server-key/status", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["fleet"]["total"] == 20
    agent_selects = [
        s for s in statements if " agents" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    assert len(agent_selects) == 1, agent_selects


@pytest.mark.asyncio
async def test_rotation_status_never_returns_key_material(client, auth_headers):
    rotate = await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    assert rotate.status_code == 201
    body = rotate.json()
    serialized = json.dumps(body)
    assert "priv" not in serialized.lower()
    assert set(body) <= {
        "active",
        "current_key_fingerprint",
        "successor_key_fingerprint",
        "started_at",
        "overlap_expires_at",
        "fleet",
    }


@pytest.mark.asyncio
async def test_pending_agents_is_empty_without_an_active_rotation(client, auth_headers, factories):
    factories.agent(status="active")
    resp = await client.get("/api/v1/agents/server-key/pending", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_pending_agents_lists_only_agents_not_on_the_successor(
    client, auth_headers, factories, db_session
):
    from datetime import timedelta

    from app.core.time import utcnow

    switched = factories.agent(status="active", hostname="switched-01")
    lagging = factories.agent(status="active", hostname="lagging-01")
    factories.agent(status="active", hostname="never-01")

    assert (
        await client.post("/api/v1/agents/server-key/rotate", headers=auth_headers)
    ).status_code == 201
    started_at = utcnow()

    switched.server_pk_successor_pinned_at = started_at + timedelta(minutes=1)
    lagging.server_pk_current_pinned_at = started_at + timedelta(minutes=1)
    db_session.flush()

    resp = await client.get("/api/v1/agents/server-key/pending", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()

    by_host = {r["hostname"]: r for r in rows}
    assert set(by_host) == {"lagging-01", "never-01"}
    assert by_host["lagging-01"]["bucket"] == "current"
    assert by_host["never-01"]["bucket"] == "unseen"


@pytest.mark.asyncio
async def test_pending_agents_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/agents/server-key/pending", headers=viewer_headers)
    assert resp.status_code == 403
