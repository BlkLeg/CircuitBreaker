"""
Tests for user management endpoints.

Routes (admin_users_router mounted at /api/v1):
  GET    /api/v1/users              — list all users (admin only)
  PATCH  /api/v1/users/{id}         — update role / is_active (admin only)
  DELETE /api/v1/users/{id}         — soft-delete / permanent (admin only)
"""

import pytest

pytestmark = pytest.mark.asyncio

_LIST = "/api/v1/admin/users"


# ── List users ────────────────────────────────────────────────────────────────


async def test_admin_can_list_users(client, auth_headers, admin_user):
    resp = await client.get(_LIST, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


async def test_list_users_gravatar_null_for_non_self(client, auth_headers, admin_user, factories):
    """L-09: gravatar_hash must be null for every user that is not the requester."""
    # Create a second user so there is always a non-self entry
    factories.user(role="viewer")
    resp = await client.get(_LIST, headers=auth_headers)
    assert resp.status_code == 200

    for item in resp.json():
        if item["id"] != admin_user.id:
            assert item["gravatar_hash"] is None, (
                f"gravatar_hash should be null for non-self user id={item['id']}"
            )


async def test_viewer_cannot_list_users(client, viewer_headers):
    resp = await client.get(_LIST, headers=viewer_headers)
    assert resp.status_code == 403


async def test_unauthenticated_cannot_list_users(client):
    resp = await client.get(_LIST)
    assert resp.status_code == 401


# ── Deactivate user ───────────────────────────────────────────────────────────


async def test_admin_can_deactivate_user(client, auth_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_admin_can_reactivate_user(client, auth_headers, factories):
    target = factories.user(role="viewer", is_active=False)
    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}",
        headers=auth_headers,
        json={"is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


# ── Viewer cannot modify users ────────────────────────────────────────────────


async def test_viewer_cannot_patch_user(client, viewer_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}",
        headers=viewer_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_user(client, viewer_headers, factories):
    target = factories.user(role="viewer")
    resp = await client.delete(
        f"/api/v1/admin/users/{target.id}",
        headers=viewer_headers,
    )
    assert resp.status_code == 403


async def test_unauthenticated_cannot_delete_user(client, factories):
    target = factories.user(role="viewer")
    resp = await client.delete(f"/api/v1/users/{target.id}")
    assert resp.status_code == 401
