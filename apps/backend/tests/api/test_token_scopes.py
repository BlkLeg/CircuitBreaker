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
async def test_service_account_jwt_with_empty_scopes_is_denied_not_promoted(client, db_session):
    from app.core.security import create_token
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db_session)
    token = create_token(0, cfg.jwt_secret, 24, scopes=[], extra_claims={"label": "empty"})
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/kb/oui", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/hardware", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_a_normal_session_is_unaffected(client, auth_headers, viewer_headers):
    assert (await client.get("/api/v1/kb/oui", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/kb/oui", headers=viewer_headers)).status_code == 403
