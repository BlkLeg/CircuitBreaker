"""
Tests for user management endpoints.

Routes (admin_users_router prefix="/admin", mounted at /api/v1):
  GET    /api/v1/admin/users              — list all users (admin only)
  POST   /api/v1/admin/users              — create user (admin only)
  PATCH  /api/v1/admin/users/{id}         — update role / is_active (admin only)
  DELETE /api/v1/admin/users/{id}         — soft-delete / permanent (admin only)
  POST   /api/v1/admin/users/{id}/unlock  — unlock locked user (admin only)
  POST   /api/v1/admin/users/{id}/masquerade — masquerade token (admin only)
  GET    /api/v1/admin/invites            — list invites (admin only)
  POST   /api/v1/admin/invites            — create invite (admin only)
  PATCH  /api/v1/admin/invites/{id}       — revoke/extend invite (admin only)
"""

import pytest

pytestmark = pytest.mark.asyncio

_ADMIN_USERS = "/api/v1/admin/users"
_ADMIN_INVITES = "/api/v1/admin/invites"


# ── List users ────────────────────────────────────────────────────────────────


async def test_admin_can_list_users(client, auth_headers, admin_user):
    resp = await client.get(_ADMIN_USERS, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


async def test_list_users_gravatar_null_for_non_self(client, auth_headers, admin_user, factories):
    """L-09: gravatar_hash must be null for every user that is not the requester."""
    # Create a second user so there is always a non-self entry
    factories.user(role="viewer")
    resp = await client.get(_ADMIN_USERS, headers=auth_headers)
    assert resp.status_code == 200

    for item in resp.json():
        if item["id"] != admin_user.id:
            assert item["gravatar_hash"] is None, (
                f"gravatar_hash should be null for non-self user id={item['id']}"
            )


async def test_viewer_cannot_list_users(client, viewer_headers):
    resp = await client.get(_ADMIN_USERS, headers=viewer_headers)
    assert resp.status_code == 403


async def test_unauthenticated_cannot_list_users(client):
    resp = await client.get(_ADMIN_USERS)
    assert resp.status_code == 401


# ── Deactivate user ───────────────────────────────────────────────────────────


async def test_admin_can_deactivate_user(client, auth_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.patch(
        f"{_ADMIN_USERS}/{target.id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_admin_can_reactivate_user(client, auth_headers, factories):
    target = factories.user(role="viewer", is_active=False)
    resp = await client.patch(
        f"{_ADMIN_USERS}/{target.id}",
        headers=auth_headers,
        json={"is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


# ── Viewer cannot modify users ────────────────────────────────────────────────


async def test_viewer_cannot_patch_user(client, viewer_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.patch(
        f"{_ADMIN_USERS}/{target.id}",
        headers=viewer_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_user(client, viewer_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.delete(
        f"{_ADMIN_USERS}/{target.id}",
        headers=viewer_headers,
    )
    assert resp.status_code == 403


async def test_unauthenticated_cannot_delete_user(client, factories):
    target = factories.user(role="viewer")
    resp = await client.delete(f"{_ADMIN_USERS}/{target.id}")
    assert resp.status_code == 401


# ── Create user (admin endpoint) ────────────────────────────────────────────


async def test_admin_can_create_user(client, auth_headers):
    resp = await client.post(
        _ADMIN_USERS,
        headers=auth_headers,
        json={
            "email": "newuser@example.com",
            "password": "StrongPass99!",
            "role": "editor",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "newuser@example.com"
    assert body["role"] == "editor"


async def test_create_duplicate_email_returns_409(client, auth_headers):
    await client.post(
        _ADMIN_USERS,
        headers=auth_headers,
        json={"email": "dup@example.com", "password": "StrongPass99!"},
    )
    resp = await client.post(
        _ADMIN_USERS,
        headers=auth_headers,
        json={"email": "dup@example.com", "password": "StrongPass99!"},
    )
    assert resp.status_code == 409


async def test_viewer_cannot_create_user(client, viewer_headers):
    resp = await client.post(
        _ADMIN_USERS,
        headers=viewer_headers,
        json={"email": "blocked@example.com", "password": "StrongPass99!"},
    )
    assert resp.status_code == 403


# ── Update user role ─────────────────────────────────────────────────────────


async def test_admin_can_update_user_role(client, auth_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.patch(
        f"{_ADMIN_USERS}/{target.id}",
        headers=auth_headers,
        json={"role": "editor"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


# ── Invites ──────────────────────────────────────────────────────────────────


async def test_admin_can_create_invite(client, auth_headers):
    resp = await client.post(
        _ADMIN_INVITES,
        headers=auth_headers,
        json={"email": "invitee@example.com", "role": "viewer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "invite_id" in body
    assert "token" in body
    assert body.get("invite_url") is not None


async def test_admin_can_list_invites(client, auth_headers):
    # Create an invite first so the list is not empty
    await client.post(
        _ADMIN_INVITES,
        headers=auth_headers,
        json={"email": "list-invite@example.com", "role": "viewer"},
    )
    resp = await client.get(_ADMIN_INVITES, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


async def test_admin_can_revoke_invite(client, auth_headers):
    create = await client.post(
        _ADMIN_INVITES,
        headers=auth_headers,
        json={"email": "revoke-me@example.com", "role": "viewer"},
    )
    invite_id = create.json()["invite_id"]
    resp = await client.patch(
        f"{_ADMIN_INVITES}/{invite_id}",
        headers=auth_headers,
        json={"action": "revoked"},
    )
    assert resp.status_code == 200


async def test_viewer_cannot_create_invite(client, viewer_headers):
    resp = await client.post(
        _ADMIN_INVITES,
        headers=viewer_headers,
        json={"email": "blocked@example.com", "role": "viewer"},
    )
    assert resp.status_code == 403


# ── Unlock user ──────────────────────────────────────────────────────────────


async def test_admin_can_unlock_user(client, auth_headers, factories):
    target = factories.user(role="viewer", login_attempts=5)
    resp = await client.post(
        f"{_ADMIN_USERS}/{target.id}/unlock",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unlocked"


# ── Masquerade ───────────────────────────────────────────────────────────────


async def test_admin_can_masquerade(client, auth_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.post(
        f"{_ADMIN_USERS}/{target.id}/masquerade",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["target_user_id"] == target.id
    assert body["expires_in_seconds"] == 900


async def test_masquerade_inactive_user_returns_400(client, auth_headers, factories):
    target = factories.user(role="viewer", is_active=False)
    resp = await client.post(
        f"{_ADMIN_USERS}/{target.id}/masquerade",
        headers=auth_headers,
    )
    assert resp.status_code == 400
