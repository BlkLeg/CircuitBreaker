"""A service-account JWT outlived every attempt to revoke it.

`POST /api/v1/auth/service-account` mints a JWT with `user_id=0` and stores a salted
hash of it in `APIToken` — the docstring says "for tracking and revocation". Resolution
never consulted that row. `resolve_optional_user_id_sync` decoded the JWT, saw
`user_id == 0`, and `_is_user_accessible` returns True unconditionally for the sentinel,
so the token authenticated on signature alone with the scopes baked into its own claims.

Deleting the row did nothing. Rotating it did nothing to the old secret, and minted an
opaque `secrets.token_urlsafe(32)` for the replacement — which resolves through the
static-token branch as `created_by`, i.e. with the rotating admin's own permissions
rather than the service account's scopes. Default expiry is 8760 hours, so a leaked
token was good for a year with no way to withdraw it.
"""

from __future__ import annotations

import pytest


async def _service_account(client, auth_headers, scopes=None, expires_at=None):
    body = {"label": "bounty-probe", "scopes": scopes or ["read:*"]}
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post("/api/v1/auth/service-account", json=body, headers=auth_headers)
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    return data["token"], data["id"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_a_live_service_account_token_is_accepted(client, auth_headers):
    """The baseline the revocation cases are measured against."""
    token, _ = await _service_account(client, auth_headers)

    resp = await client.get("/api/v1/hardware", headers=_bearer(token))

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_revoking_a_service_account_stops_its_token(client, auth_headers):
    token, token_id = await _service_account(client, auth_headers)
    assert (await client.get("/api/v1/hardware", headers=_bearer(token))).status_code == 200

    deleted = await client.delete(f"/api/v1/auth/api-tokens/{token_id}", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text

    resp = await client.get("/api/v1/hardware", headers=_bearer(token))

    assert resp.status_code == 401, (
        f"a revoked service-account token still authenticated ({resp.status_code}); "
        "deleting the APIToken row must withdraw the JWT"
    )


@pytest.mark.asyncio
async def test_rotating_a_service_account_stops_the_old_token(client, auth_headers):
    token, token_id = await _service_account(client, auth_headers)
    assert (await client.get("/api/v1/hardware", headers=_bearer(token))).status_code == 200

    rotated = await client.post(f"/api/v1/auth/api-tokens/{token_id}/rotate", headers=auth_headers)
    assert rotated.status_code == 200, rotated.text

    resp = await client.get("/api/v1/hardware", headers=_bearer(token))

    assert resp.status_code == 401, (
        f"the pre-rotation token still authenticated ({resp.status_code})"
    )


@pytest.mark.asyncio
async def test_the_rotated_service_account_token_keeps_the_account_scopes(client, auth_headers):
    """The replacement must still be the service account, not the admin who rotated it.

    Rotation minted an opaque string, which resolves through the static-token branch as
    `created_by` — so the rotated credential silently gained the rotating admin's own
    permissions. A read-only service account came back able to write.
    """
    token, token_id = await _service_account(client, auth_headers, scopes=["read:*"])

    rotated = await client.post(f"/api/v1/auth/api-tokens/{token_id}/rotate", headers=auth_headers)
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]

    assert (await client.get("/api/v1/hardware", headers=_bearer(new_token))).status_code == 200

    wrote = await client.post(
        "/api/v1/hardware",
        json={"name": "read-only-account-should-not-create-this"},
        headers=_bearer(new_token),
    )
    assert wrote.status_code == 403, (
        f"a read-only service account wrote after rotation ({wrote.status_code}); the "
        "replacement carried the rotating admin's permissions instead of its own scopes"
    )
