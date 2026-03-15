"""
Tests for admin user management endpoints:
  GET    /api/v1/admin/users
  POST   /api/v1/admin/users
  PATCH  /api/v1/admin/users/{id}
  DELETE /api/v1/admin/users/{id}
  POST   /api/v1/admin/users/{id}/unlock
  POST   /api/v1/admin/users/{id}/masquerade
  POST   /api/v1/admin/invites
  GET    /api/v1/admin/invites
  PATCH  /api/v1/admin/invites/{id}
  GET    /api/v1/admin/user-actions/{id}
"""

import pytest

ADMIN_USERS_URL = "/api/v1/admin/users"
ADMIN_INVITES_URL = "/api/v1/admin/invites"


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


class TestAdminListUsers:
    @pytest.mark.asyncio
    async def test_list_users(self, client, auth_headers):
        """GET /admin/users returns list of users."""
        resp = await client.get(ADMIN_USERS_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1  # at least the admin user from auth_headers

    @pytest.mark.asyncio
    async def test_list_users_viewer_forbidden(self, client, viewer_headers):
        """Viewer cannot list users."""
        resp = await client.get(ADMIN_USERS_URL, headers=viewer_headers)
        assert resp.status_code == 403


class TestAdminCreateUser:
    @pytest.mark.asyncio
    async def test_create_user(self, client, auth_headers):
        """POST /admin/users creates a user with email/password/role."""
        resp = await client.post(
            ADMIN_USERS_URL,
            headers=auth_headers,
            json={
                "email": "newadmin-created@test.local",
                "password": "StrongPassword123!",
                "role": "editor",
            },
        )
        assert resp.status_code == 200, f"Create user failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["email"] == "newadmin-created@test.local"
        assert body["role"] == "editor"
        assert "id" in body

    @pytest.mark.asyncio
    async def test_create_duplicate_email_returns_409(self, client, auth_headers, factories):
        """Creating a user with an existing email returns 409."""
        existing = factories.user(role="viewer")
        resp = await client.post(
            ADMIN_USERS_URL,
            headers=auth_headers,
            json={
                "email": existing.email,
                "password": "StrongPassword123!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 409, f"Duplicate email should return 409, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_user(self, client, viewer_headers):
        """Viewer cannot create users."""
        resp = await client.post(
            ADMIN_USERS_URL,
            headers=viewer_headers,
            json={
                "email": "viewer-attempt@test.local",
                "password": "StrongPassword123!",
                "role": "viewer",
            },
        )
        assert resp.status_code == 403


class TestAdminUpdateUser:
    @pytest.mark.asyncio
    async def test_update_role(self, client, auth_headers, factories):
        """PATCH /admin/users/{id} updates user role."""
        user = factories.user(role="viewer")
        resp = await client.patch(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=auth_headers,
            json={"role": "editor"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "editor"

    @pytest.mark.asyncio
    async def test_deactivate_user(self, client, auth_headers, factories):
        """PATCH /admin/users/{id} with is_active=False deactivates user."""
        user = factories.user(role="viewer")
        resp = await client.patch(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_active"] is False

    @pytest.mark.asyncio
    async def test_reactivate_user(self, client, auth_headers, factories):
        """PATCH /admin/users/{id} with is_active=True reactivates user."""
        user = factories.user(role="viewer", is_active=False)
        resp = await client.patch(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=auth_headers,
            json={"is_active": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_active"] is True

    @pytest.mark.asyncio
    async def test_viewer_cannot_update_user(self, client, viewer_headers, factories):
        """Viewer cannot update users."""
        user = factories.user(role="viewer")
        resp = await client.patch(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=viewer_headers,
            json={"role": "admin"},
        )
        assert resp.status_code == 403


class TestAdminDeleteUser:
    @pytest.mark.asyncio
    async def test_soft_delete_user(self, client, auth_headers, factories):
        """DELETE /admin/users/{id} soft-deletes (deactivates) user."""
        user = factories.user(role="viewer")
        resp = await client.delete(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_viewer_cannot_delete_user(self, client, viewer_headers, factories):
        """Viewer cannot delete users."""
        user = factories.user(role="viewer")
        resp = await client.delete(
            f"{ADMIN_USERS_URL}/{user.id}",
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Unlock
# ---------------------------------------------------------------------------


class TestAdminUnlockUser:
    @pytest.mark.asyncio
    async def test_unlock_user(self, client, auth_headers, factories):
        """POST /admin/users/{id}/unlock returns success."""
        user = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{user.id}/unlock",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unlocked"

    @pytest.mark.asyncio
    async def test_unlock_nonexistent_user_returns_404(self, client, auth_headers):
        """Unlocking a nonexistent user returns 404."""
        resp = await client.post(
            f"{ADMIN_USERS_URL}/999999/unlock",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Masquerade
# ---------------------------------------------------------------------------


class TestAdminMasquerade:
    @pytest.mark.asyncio
    async def test_masquerade_returns_token(self, client, auth_headers, factories):
        """POST /admin/users/{id}/masquerade returns a short-lived token."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/masquerade",
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"Masquerade failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "token" in body
        assert body["target_user_id"] == target.id
        assert body["expires_in_seconds"] == 15 * 60

    @pytest.mark.asyncio
    async def test_masquerade_inactive_user_returns_400(self, client, auth_headers, factories):
        """Cannot masquerade as an inactive user."""
        target = factories.user(role="viewer", is_active=False)
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/masquerade",
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_masquerade_nonexistent_returns_404(self, client, auth_headers):
        """Masquerade for nonexistent user returns 404."""
        resp = await client.post(
            f"{ADMIN_USERS_URL}/999999/masquerade",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_viewer_cannot_masquerade(self, client, viewer_headers, factories):
        """Viewer cannot masquerade."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/masquerade",
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


class TestAdminInvites:
    @pytest.mark.asyncio
    async def test_create_invite(self, client, auth_headers):
        """POST /admin/invites creates an invite and returns token + url."""
        resp = await client.post(
            ADMIN_INVITES_URL,
            headers=auth_headers,
            json={"email": "invite-test@test.local", "role": "viewer"},
        )
        assert resp.status_code == 200, f"Invite creation failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "invite_id" in body
        assert "token" in body
        assert "invite_url" in body

    @pytest.mark.asyncio
    async def test_list_invites(self, client, auth_headers):
        """GET /admin/invites returns list of invites."""
        # Create one first
        await client.post(
            ADMIN_INVITES_URL,
            headers=auth_headers,
            json={"email": "list-invite@test.local", "role": "editor"},
        )
        resp = await client.get(ADMIN_INVITES_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 1

    @pytest.mark.asyncio
    async def test_revoke_invite(self, client, auth_headers):
        """PATCH /admin/invites/{id} with action=revoked revokes the invite."""
        create_resp = await client.post(
            ADMIN_INVITES_URL,
            headers=auth_headers,
            json={"email": "revoke-invite@test.local", "role": "viewer"},
        )
        invite_id = create_resp.json()["invite_id"]

        resp = await client.patch(
            f"{ADMIN_INVITES_URL}/{invite_id}",
            headers=auth_headers,
            json={"action": "revoked"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_invite(self, client, viewer_headers):
        """Viewer cannot create invites."""
        resp = await client.post(
            ADMIN_INVITES_URL,
            headers=viewer_headers,
            json={"email": "viewer-invite@test.local", "role": "viewer"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_list_invites(self, client, viewer_headers):
        """Viewer cannot list invites."""
        resp = await client.get(ADMIN_INVITES_URL, headers=viewer_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User actions (audit log)
# ---------------------------------------------------------------------------


class TestAdminUserActions:
    @pytest.mark.asyncio
    async def test_get_user_actions(self, client, auth_headers, factories):
        """GET /admin/user-actions/{id} returns audit entries."""
        user = factories.user(role="viewer")
        resp = await client.get(
            f"/api/v1/admin/user-actions/{user.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "logs" in body
        assert "total_count" in body
        assert isinstance(body["logs"], list)

    @pytest.mark.asyncio
    async def test_viewer_cannot_get_user_actions(self, client, viewer_headers, factories):
        """Viewer cannot access user actions."""
        user = factories.user(role="viewer")
        resp = await client.get(
            f"/api/v1/admin/user-actions/{user.id}",
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin Password Reset
# ---------------------------------------------------------------------------


class TestAdminResetPassword:
    @pytest.mark.asyncio
    async def test_reset_password_autogenerate(self, client, auth_headers, factories):
        """POST /admin/users/{id}/reset-password auto-generates a temp password."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/reset-password",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["force_password_change"] is True
        assert isinstance(body["temporary_password"], str)
        assert len(body["temporary_password"]) >= 20

    @pytest.mark.asyncio
    async def test_reset_password_custom(self, client, auth_headers, factories):
        """POST /admin/users/{id}/reset-password accepts a custom password."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/reset-password",
            headers=auth_headers,
            json={"custom_password": "MyCustomPass99!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["force_password_change"] is True
        assert body["temporary_password"] == "MyCustomPass99!"

    @pytest.mark.asyncio
    async def test_reset_password_custom_too_short(self, client, auth_headers, factories):
        """Custom password under 8 chars is rejected."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/reset-password",
            headers=auth_headers,
            json={"custom_password": "short"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_password_sets_force_change(self, client, auth_headers, factories):
        """After admin reset, user login triggers force-change flow."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/reset-password",
            headers=auth_headers,
            json={"custom_password": "ResetTemp123!"},
        )
        assert resp.status_code == 200

        # Login with the new temp password — should get force-change response
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": target.email, "password": "ResetTemp123!"},
        )
        assert login_resp.status_code == 200
        body = login_resp.json()
        assert body.get("requires_change") is True
        assert "change_token" in body

    @pytest.mark.asyncio
    async def test_reset_password_viewer_forbidden(self, client, viewer_headers, factories):
        """Viewer cannot reset passwords."""
        target = factories.user(role="viewer")
        resp = await client.post(
            f"{ADMIN_USERS_URL}/{target.id}/reset-password",
            headers=viewer_headers,
            json={},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_reset_password_nonexistent_user(self, client, auth_headers):
        """Reset password for non-existent user returns 404."""
        resp = await client.post(
            f"{ADMIN_USERS_URL}/99999/reset-password",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 404
