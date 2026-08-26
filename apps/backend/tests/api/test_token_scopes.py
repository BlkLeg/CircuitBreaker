"""B1: token scopes must restrict role-guarded routes, not only scope-guarded ones.

Before this, a token created by an admin passed every require_role gate as that
admin, and a service-account JWT passed as a superuser before any scope check
ran (rbac.py:141) — so scopes narrowed only the two require_scope checks that
exist in the whole backend. See INC-04 / INC-14.
"""

from __future__ import annotations

import pytest

from app.core.security import create_salted_api_token_hash
from app.db.models import APIToken


def _token_headers(db_session, factories, raw_token: str, scopes) -> dict[str, str]:
    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash(raw_token),
            label="scope test",
            created_by=owner.id,
            scopes=scopes,
        )
    )
    db_session.flush()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.mark.asyncio
async def test_read_only_token_is_refused_on_an_admin_route(client, db_session, factories):
    headers = _token_headers(db_session, factories, "tok-readonly", ["read:*"])
    resp = await client.get("/api/v1/kb/oui", headers=headers)
    assert resp.status_code == 403, (
        "a read:* token reached an admin-only route — this is the escalation B1 closes"
    )


@pytest.mark.asyncio
async def test_read_only_token_is_allowed_on_a_read_route(client, db_session, factories):
    headers = _token_headers(db_session, factories, "tok-readonly-2", ["read:*"])
    resp = await client.get("/api/v1/hardware", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_full_access_token_is_allowed_everywhere(client, db_session, factories):
    headers = _token_headers(db_session, factories, "tok-full", ["*:*"])
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_admin_only_scope_does_not_satisfy_a_read_gate(client, db_session, factories):
    headers = _token_headers(db_session, factories, "tok-adminonly", ["admin:*"])
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_legacy_scopeless_token_still_authenticates_as_its_creator(
    client, db_session, factories
):
    headers = _token_headers(db_session, factories, "tok-legacy", [])
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_legacy_scopeless_token_inherits_a_viewers_limits_too(client, db_session, factories):
    owner = factories.user(role="viewer")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash("tok-legacy-viewer"),
            label="legacy viewer token",
            created_by=owner.id,
            scopes=[],
        )
    )
    db_session.flush()
    headers = {"Authorization": "Bearer tok-legacy-viewer"}
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_service_account_jwt_with_empty_scopes_is_denied_not_promoted(
    client, db_session, admin_user
):
    # admin_user only owns the APIToken row the service account needs; the request
    # below still authenticates as the service account, not as that admin.
    from tests.helpers.service_account import mint_service_account_token

    token = mint_service_account_token(db_session, scopes=[], label="empty")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_a_normal_session_is_unaffected(client, auth_headers, viewer_headers):
    assert (await client.get("/api/v1/kb/oui", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=viewer_headers)).status_code == 403


# ── B2/B3/B4: catalog, presets, validation ────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_catalog_is_served_to_admins(client, auth_headers):
    resp = await client.get("/api/v1/auth/scopes", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert {s["scope"] for s in body["scopes"]} >= {"read:*", "write:telemetry", "*:*"}
    assert [p["key"] for p in body["presets"]] == [
        "read_only",
        "telemetry_ingest",
        "read_write",
        "full_access",
    ]


def test_full_access_preset_is_star_star_not_admin_star():
    from app.core.token_scopes import SCOPE_PRESETS

    full = next(p for p in SCOPE_PRESETS if p["key"] == "full_access")
    assert full["scopes"] == ["*:*"]


def test_catalog_covers_every_scope_the_presets_grant():
    from app.core.token_scopes import GRANTABLE_SCOPES, SCOPE_PRESETS

    for preset in SCOPE_PRESETS:
        for scope in preset["scopes"]:
            assert scope in GRANTABLE_SCOPES, f"{preset['key']} grants uncatalogued {scope}"


def test_catalog_matches_the_role_scope_requirements():
    from app.core.rbac import ROLE_SCOPE_REQUIREMENT
    from app.core.token_scopes import GRANTABLE_SCOPES

    for action, resource in ROLE_SCOPE_REQUIREMENT.values():
        assert f"{action}:{resource}" in GRANTABLE_SCOPES


@pytest.mark.asyncio
async def test_service_account_rejects_an_unknown_scope(client, auth_headers):
    resp = await client.post(
        "/api/v1/auth/service-account",
        headers=auth_headers,
        json={"label": "typo", "scopes": ["read:hardwrae"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_service_account_rejects_an_empty_scope_list(client, auth_headers):
    resp = await client.post(
        "/api/v1/auth/service-account",
        headers=auth_headers,
        json={"label": "empty", "scopes": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_token_accepts_and_stores_scopes(client, auth_headers, db_session):
    from app.db.models import APIToken

    resp = await client.post(
        "/api/v1/auth/api-token",
        headers=auth_headers,
        json={"label": "ci", "scopes": ["read:*"]},
    )
    assert resp.status_code == 200
    row = db_session.get(APIToken, resp.json()["id"])
    assert row.scopes == ["read:*"]


@pytest.mark.asyncio
async def test_api_token_without_scopes_defaults_to_the_creators_scopes(
    client, auth_headers, db_session
):
    from app.db.models import APIToken

    resp = await client.post(
        "/api/v1/auth/api-token", headers=auth_headers, json={"label": "inherit"}
    )
    assert resp.status_code == 200
    row = db_session.get(APIToken, resp.json()["id"])
    assert row.scopes, "scopes must not be empty"
    assert "admin:*" in row.scopes
