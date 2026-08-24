"""B5–B7: fleet-wide token inventory, rotation, revocation. INC-14."""

from __future__ import annotations

import pytest

from app.core.security import create_salted_api_token_hash
from app.db.models import APIToken


def _token_for(db_session, owner, label: str, scopes=None) -> APIToken:
    row = APIToken(
        token_hash=create_salted_api_token_hash(f"raw-{label}"),
        label=label,
        created_by=owner.id,
        scopes=scopes if scopes is not None else ["read:*"],
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.mark.asyncio
async def test_list_defaults_to_own_tokens(client, auth_headers, db_session, factories):
    other = factories.user(role="admin")
    _token_for(db_session, other, "someone-elses")
    resp = await client.get("/api/v1/auth/api-tokens", headers=auth_headers)
    assert resp.status_code == 200
    assert all(t["label"] != "someone-elses" for t in resp.json())


@pytest.mark.asyncio
async def test_list_all_shows_every_admins_tokens(client, auth_headers, db_session, factories):
    other = factories.user(role="admin", email="peer@example.com")
    _token_for(db_session, other, "someone-elses")
    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)
    assert resp.status_code == 200
    labels = [t["label"] for t in resp.json()]
    assert "someone-elses" in labels


@pytest.mark.asyncio
async def test_list_items_carry_scopes_and_creator(client, auth_headers, db_session, factories):
    owner = factories.user(role="admin", email="owner@example.com")
    _token_for(db_session, owner, "ci-deploy", ["read:*", "write:telemetry"])
    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)
    item = next(t for t in resp.json() if t["label"] == "ci-deploy")
    assert item["scopes"] == ["read:*", "write:telemetry"]
    assert item["created_by"] == owner.id
    assert item["created_by_name"]


@pytest.mark.asyncio
async def test_service_accounts_are_flagged_by_a_field_not_a_label_prefix(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="sa@example.com")
    _token_for(db_session, owner, "[Service Account] metrics")
    _token_for(db_session, owner, "plain-token")
    resp = await client.get("/api/v1/auth/api-tokens?scope=all", headers=auth_headers)
    by_label = {t["label"]: t for t in resp.json()}
    assert by_label["[Service Account] metrics"]["is_service_account"] is True
    assert by_label["plain-token"]["is_service_account"] is False


@pytest.mark.asyncio
async def test_an_admin_can_revoke_another_admins_token(
    client, auth_headers, db_session, factories
):
    other = factories.user(role="admin", email="peer2@example.com")
    row = _token_for(db_session, other, "peers-token")
    resp = await client.delete(f"/api/v1/auth/api-tokens/{row.id}", headers=auth_headers)
    assert resp.status_code == 204
    assert db_session.get(APIToken, row.id) is None


@pytest.mark.asyncio
async def test_revoking_a_missing_token_is_404(client, auth_headers):
    resp = await client.delete("/api/v1/auth/api-tokens/999999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_token_admin_requires_admin(client, viewer_headers):
    assert (await client.get("/api/v1/auth/api-tokens", headers=viewer_headers)).status_code == 403


@pytest.mark.asyncio
async def test_rotation_issues_a_new_secret_and_kills_the_old_one(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="rot@example.com")
    row = _token_for(db_session, owner, "ci-deploy", ["read:*"])
    old_id = row.id
    resp = await client.post(f"/api/v1/auth/api-tokens/{old_id}/rotate", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["id"] != old_id
    assert db_session.get(APIToken, old_id) is None


@pytest.mark.asyncio
async def test_rotation_preserves_label_and_scopes(client, auth_headers, db_session, factories):
    owner = factories.user(role="admin", email="rot2@example.com")
    row = _token_for(db_session, owner, "collector", ["read:*", "write:telemetry"])
    resp = await client.post(f"/api/v1/auth/api-tokens/{row.id}/rotate", headers=auth_headers)
    new_row = db_session.get(APIToken, resp.json()["id"])
    assert new_row.label == "collector"
    assert new_row.scopes == ["read:*", "write:telemetry"]


@pytest.mark.asyncio
async def test_the_old_secret_stops_authenticating_after_rotation(
    client, auth_headers, db_session, factories
):
    owner = factories.user(role="admin", email="rot3@example.com")
    row = _token_for(db_session, owner, "ci-old", ["read:*"])
    old_headers = {"Authorization": "Bearer raw-ci-old"}
    assert (await client.get("/api/v1/hardware", headers=old_headers)).status_code == 200
    await client.post(f"/api/v1/auth/api-tokens/{row.id}/rotate", headers=auth_headers)
    assert (await client.get("/api/v1/hardware", headers=old_headers)).status_code == 401


@pytest.mark.asyncio
async def test_rotating_a_missing_token_is_404(client, auth_headers):
    resp = await client.post("/api/v1/auth/api-tokens/999999/rotate", headers=auth_headers)
    assert resp.status_code == 404
