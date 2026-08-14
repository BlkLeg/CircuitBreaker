"""Routes that serve monitor state outside `/monitors` must carry its rules.

SEC-08 put a `read:*` scope and a tenant rule on `/monitors`, but monitor state
is also reachable through the integrations listings and the map's node rollups.
Those were left on a plain `require_auth`, which ignores token scopes — so a
write-only token could read what `/monitors` would have refused it, and the map
handed out rollups for targets belonging to another tenant.

Each test here is the side channel, not the front door: `/monitors` itself is
covered by tests/api/test_monitor_api.py.
"""

import pytest

pytestmark = pytest.mark.asyncio


def _write_only_token(factories, db_session, label):
    """An API token carrying `write:*` and nothing else."""
    from app.core.security import create_salted_api_token_hash
    from app.db.models import APIToken

    secret = f"side-channel-{label}"
    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash(secret),
            label=f"write-only {label}",
            created_by=owner.id,
            scopes=["write:*"],
        )
    )
    db_session.flush()
    return {"Authorization": f"Bearer {secret}"}


# ── Integrations monitor listings ────────────────────────────────────────────


async def test_all_integration_monitors_reject_scoped_token_without_read(
    client, factories, db_session
):
    headers = _write_only_token(factories, db_session, "all")
    resp = await client.get("/api/v1/integrations/monitors", headers=headers)
    assert resp.status_code == 403, resp.text


async def test_per_integration_monitors_reject_scoped_token_without_read(
    client, factories, db_session
):
    integ = factories.integration()
    db_session.flush()
    headers = _write_only_token(factories, db_session, "per-integration")
    resp = await client.get(f"/api/v1/integrations/{integ.id}/monitors", headers=headers)
    assert resp.status_code == 403, resp.text


async def test_native_monitors_path_rejects_scoped_token_without_read(
    client, factories, db_session
):
    """Covers the path, whichever route currently answers it.

    Note `/native/monitors` is declared *after* `/{integration_id}/monitors`, so
    FastAPI matches the parameterized route first and `list_native_monitors` is
    unreachable — a reader gets 422 (`"native"` is not an int), not a listing.
    That shadowing is a pre-existing routing bug, not a SEC finding; the scope
    is asserted here so the path stays guarded whichever route wins once it is
    fixed.
    """
    headers = _write_only_token(factories, db_session, "native")
    resp = await client.get("/api/v1/integrations/native/monitors", headers=headers)
    assert resp.status_code == 403, resp.text


async def test_integration_monitor_listings_still_work_for_a_reader(
    client, auth_headers, factories, db_session
):
    """The scope is a filter on who may read, not a break of the listing."""
    integ = factories.integration()
    db_session.flush()
    for path in (
        "/api/v1/integrations/monitors",
        f"/api/v1/integrations/{integ.id}/monitors",
    ):
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        assert isinstance(resp.json(), list)


# ── Map node rollups ─────────────────────────────────────────────────────────


async def test_topology_rollups_hide_monitors_belonging_to_another_tenant(
    client, db_session, factories
):
    """A reader in tenant A must not learn tenant B's monitor state from the map.

    The node itself stays on the map under its own inventory rules; only the
    rollup is withheld, so it renders exactly as an unmonitored node would.
    """
    from app.services import monitor_service

    tenant_a = _tenant(db_session, "side-channel-a")
    tenant_b = _tenant(db_session, "side-channel-b")

    hw_b = factories.hardware(ip_address="192.0.2.90", tenant_id=tenant_b)
    db_session.commit()
    assert monitor_service.create_target_monitor(db_session, "hardware", hw_b.id)

    headers = await _login_headers(client, factories, db_session, tenant_id=tenant_a)

    resp = await client.get("/api/v1/graph/topology", headers=headers)
    assert resp.status_code == 200, resp.text
    node = next(n for n in resp.json()["nodes"] if n["id"] == f"hw-{hw_b.id}")

    assert node["monitor_id"] is None
    assert node["monitor_status"] is None
    assert node["monitor_enabled"] is None


async def test_topology_rollups_are_visible_within_the_readers_own_tenant(
    client, db_session, factories
):
    from app.services import monitor_service

    tenant = _tenant(db_session, "side-channel-own")
    hw = factories.hardware(ip_address="192.0.2.91", tenant_id=tenant)
    db_session.commit()
    assert monitor_service.create_target_monitor(db_session, "hardware", hw.id)

    headers = await _login_headers(client, factories, db_session, tenant_id=tenant)

    resp = await client.get("/api/v1/graph/topology", headers=headers)
    assert resp.status_code == 200, resp.text
    node = next(n for n in resp.json()["nodes"] if n["id"] == f"hw-{hw.id}")

    assert node["monitor_id"] is not None
    assert node["monitor_status"] == "pending"


def _tenant(db_session, name):
    import secrets

    from app.db.models import Tenant

    tenant = Tenant(name=f"{name}-{secrets.token_hex(4)}")
    db_session.add(tenant)
    db_session.flush()
    return tenant.id


async def _login_headers(client, factories, db_session, *, tenant_id):
    user = factories.user(role="admin", tenant_id=tenant_id)
    db_session.flush()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "TestPassword123!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
