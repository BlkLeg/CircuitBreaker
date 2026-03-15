"""
Comprehensive authentication tests for Circuit Breaker backend.

Covers: login, wrong credentials, protected routes, token validation,
logout+revoke, timing side-channel, expired JWT, wrong audience, RBAC.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest

from app.core.security import SESSION_AUDIENCE

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.mark.asyncio
    async def test_successful_login_returns_token(self, client, factories):
        user = factories.user(role="admin")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body, f"Expected 'token' key, got: {list(body.keys())}"
        assert "user" in body
        assert isinstance(body["token"], str)
        assert len(body["token"]) > 10

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, client, factories):
        user = factories.user(role="viewer")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "WrongPassword!999"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_password_does_not_reveal_email_existence(self, client, factories):
        """Error message must be the same whether the email exists or not."""
        user = factories.user(role="viewer")
        real_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "totally-wrong-pw!"},
        )
        fake_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nonexistent.invalid", "password": "totally-wrong-pw!"},
        )
        assert real_resp.status_code == 401
        assert fake_resp.status_code == 401
        # Both responses must carry the same generic message
        real_msg = real_resp.json().get("detail", "")
        fake_msg = fake_resp.json().get("detail", "")
        assert real_msg == fake_msg, (
            f"Error messages differ — leaks email existence.\n"
            f"Real user msg : {real_msg!r}\n"
            f"Fake user msg : {fake_msg!r}"
        )

    @pytest.mark.asyncio
    async def test_nonexistent_user_returns_401(self, client):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@nowhere.invalid", "password": "doesntmatter1!"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected routes — no token / bad token
# ---------------------------------------------------------------------------


class TestUnauthenticatedAccess:
    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, client):
        resp = await client.get("/api/v1/hardware")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_garbage_token_returns_401(self, client):
        resp = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": "Bearer this.is.garbage"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_bearer_header_returns_401(self, client):
        resp = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": "NotBearer sometoken"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout + token revocation
# ---------------------------------------------------------------------------


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_returns_204(self, client, auth_headers):
        resp = await client.post("/api/v1/auth/logout", headers=auth_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_token_rejected_after_logout(self, client, factories):
        user = factories.user(role="admin")
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        csrf = login_resp.cookies.get("cb_csrf", "test-csrf")
        headers = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}

        # Confirm token works before logout
        pre_resp = await client.get("/api/v1/hardware", headers=headers)
        assert pre_resp.status_code == 200

        # Logout
        logout_resp = await client.post("/api/v1/auth/logout", headers=headers)
        assert logout_resp.status_code == 204

        # Same token must now be rejected
        post_resp = await client.get("/api/v1/hardware", headers=headers)
        assert post_resp.status_code == 401, (
            "Token still accepted after logout — session revocation is broken"
        )


# ---------------------------------------------------------------------------
# Timing attack — bcrypt constant-time comparison
# ---------------------------------------------------------------------------


class TestTimingSideChannel:
    @pytest.mark.asyncio
    @pytest.mark.security
    @pytest.mark.slow
    async def test_login_timing_real_vs_fake_user(self, client, factories):
        """
        bcrypt is intentionally slow (~300ms).  The server must take a similar
        amount of time regardless of whether the email exists, so an attacker
        cannot enumerate users via response timing.

        Tolerance: 500ms (bcrypt variance is high under load).
        """
        real_user = factories.user(role="viewer")

        t0 = time.monotonic()
        await client.post(
            "/api/v1/auth/login",
            json={"email": real_user.email, "password": "WrongPassword!999"},
        )
        real_user_time = time.monotonic() - t0

        t0 = time.monotonic()
        await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nonexistent.invalid", "password": "WrongPassword!999"},
        )
        fake_user_time = time.monotonic() - t0

        diff = abs(real_user_time - fake_user_time)
        assert diff < 0.5, (
            f"Timing difference {diff:.3f}s exceeds 500ms threshold — "
            f"possible user-enumeration side-channel. "
            f"real={real_user_time:.3f}s fake={fake_user_time:.3f}s"
        )


# ---------------------------------------------------------------------------
# JWT edge cases — expired / wrong audience
# ---------------------------------------------------------------------------


class TestJWTEdgeCases:
    def _make_jwt(self, payload: dict) -> str:
        secret = os.environ["CB_JWT_SECRET"]
        return pyjwt.encode(payload, secret, algorithm="HS256")

    @pytest.mark.asyncio
    async def test_expired_jwt_returns_401(self, client, factories):
        user = factories.user(role="admin")
        expired_token = self._make_jwt(
            {
                "user_id": user.id,
                "sub": str(user.id),
                "aud": SESSION_AUDIENCE,
                "exp": datetime.now(UTC) - timedelta(hours=1),
                "iat": datetime.now(UTC) - timedelta(hours=2),
            }
        )
        resp = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_password_reset_token_rejected_on_hardware_route(self, client, factories):
        """A token minted for password-reset (aud=cb:change-password) must not
        grant access to the hardware API."""
        user = factories.user(role="admin")
        change_token = self._make_jwt(
            {
                "user_id": user.id,
                "sub": str(user.id),
                "aud": "cb:change-password",
                "exp": datetime.now(UTC) + timedelta(hours=1),
                "iat": datetime.now(UTC),
            }
        )
        resp = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": f"Bearer {change_token}"},
        )
        assert resp.status_code == 401, (
            "Password-reset token must not be accepted on /api/v1/hardware"
        )


# ---------------------------------------------------------------------------
# RBAC — viewer role
# ---------------------------------------------------------------------------


class TestViewerRBAC:
    @pytest.mark.asyncio
    async def test_viewer_can_get_hardware(self, client, viewer_headers):
        resp = await client.get("/api/v1/hardware", headers=viewer_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_viewer_cannot_post_hardware(self, client, viewer_headers):
        resp = await client.post(
            "/api/v1/hardware",
            headers=viewer_headers,
            json={"name": "viewer-created-device"},
        )
        assert resp.status_code == 403, (
            f"Viewer must not be able to create hardware, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    @pytest.mark.asyncio
    async def test_bootstrap_initialize_creates_admin(self, client, db_session):
        """POST /bootstrap/initialize creates admin when no users exist."""
        from app.db.models import AppSettings, User

        # Clear users and disable auth so bootstrap considers itself fresh
        db_session.query(User).delete()
        cfg = db_session.query(AppSettings).first()
        if cfg is None:
            cfg = AppSettings(id=1)
            db_session.add(cfg)
        cfg.auth_enabled = False
        cfg.registration_open = True
        db_session.flush()

        resp = await client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": "bootstrap-admin@test.local",
                "password": "BootstrapPass123!",
                "display_name": "Bootstrap Admin",
                "theme_preset": "dark",
            },
        )
        # First bootstrap should succeed (200 or 201)
        assert resp.status_code in (200, 201), f"Bootstrap failed: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "token" in body or "user" in body

    @pytest.mark.asyncio
    async def test_bootstrap_second_attempt_returns_409(self, client, db_session):
        """Second bootstrap attempt returns 409 when admin already exists."""
        from app.db.models import AppSettings

        # auth_enabled is True from app_cfg fixture, so bootstrap is complete
        cfg = db_session.query(AppSettings).first()
        assert cfg is not None
        assert cfg.auth_enabled is True

        resp = await client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": "boot-second@test.local",
                "password": "BootstrapPass123!",
                "display_name": "Second Admin",
                "theme_preset": "dark",
            },
        )
        assert resp.status_code == 409, (
            f"Second bootstrap should return 409, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.asyncio
    async def test_register_when_open(self, client, db_session, factories):
        """POST /auth/register succeeds when registration_open=True."""
        from app.db.models import AppSettings

        # Ensure at least one user exists (bootstrap complete)
        factories.user(role="admin")

        cfg = db_session.query(AppSettings).first()
        if cfg is None:
            cfg = AppSettings(id=1)
            db_session.add(cfg)
        cfg.registration_open = True
        db_session.flush()

        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser-reg@test.local",
                "password": "RegisterPass123!",
            },
        )
        assert resp.status_code == 200, (
            f"Registration should succeed when open: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert "token" in body

    @pytest.mark.asyncio
    async def test_register_when_closed_returns_403(self, client, db_session, factories):
        """POST /auth/register returns 403 when registration_open=False."""
        from app.db.models import AppSettings

        # Ensure at least one user exists (bootstrap complete)
        factories.user(role="admin")

        cfg = db_session.query(AppSettings).first()
        if cfg is None:
            cfg = AppSettings(id=1)
            db_session.add(cfg)
        cfg.registration_open = False
        db_session.flush()

        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "blocked-reg@test.local",
                "password": "RegisterPass123!",
            },
        )
        assert resp.status_code == 403, (
            f"Registration should be blocked when closed, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Profile — GET /auth/me
# ---------------------------------------------------------------------------


class TestProfile:
    @pytest.mark.asyncio
    async def test_get_me_returns_profile(self, client, auth_headers):
        """GET /auth/me returns current user profile."""
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "email" in body
        assert "role" in body
        assert "id" in body

    @pytest.mark.asyncio
    async def test_get_me_unauthenticated_returns_401(self, client):
        """GET /auth/me without token returns 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API Tokens — create, list, revoke
# ---------------------------------------------------------------------------


class TestAPITokens:
    @pytest.mark.asyncio
    async def test_create_api_token(self, client, auth_headers):
        """POST /auth/api-token creates a token and returns the raw value once."""
        resp = await client.post(
            "/api/v1/auth/api-token",
            headers=auth_headers,
            json={"label": "ci-test-token"},
        )
        assert resp.status_code in (200, 201), (
            f"API token creation failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert "token" in body, f"Response missing 'token' key: {body.keys()}"
        assert "id" in body
        assert body["label"] == "ci-test-token"

    @pytest.mark.asyncio
    async def test_list_api_tokens(self, client, auth_headers):
        """GET /auth/api-tokens returns list of created tokens."""
        # Create one first
        await client.post(
            "/api/v1/auth/api-token",
            headers=auth_headers,
            json={"label": "list-test-token"},
        )
        resp = await client.get("/api/v1/auth/api-tokens", headers=auth_headers)
        assert resp.status_code == 200
        tokens = resp.json()
        assert isinstance(tokens, list)
        assert any(t["label"] == "list-test-token" for t in tokens)

    @pytest.mark.asyncio
    async def test_revoke_api_token(self, client, auth_headers):
        """DELETE /auth/api-tokens/{id} revokes the token."""
        create_resp = await client.post(
            "/api/v1/auth/api-token",
            headers=auth_headers,
            json={"label": "to-revoke"},
        )
        token_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/auth/api-tokens/{token_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Verify it no longer appears
        list_resp = await client.get("/api/v1/auth/api-tokens", headers=auth_headers)
        remaining_ids = [t["id"] for t in list_resp.json()]
        assert token_id not in remaining_ids

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_api_token(self, client, viewer_headers):
        """Viewer role cannot create API tokens (admin only)."""
        resp = await client.post(
            "/api/v1/auth/api-token",
            headers=viewer_headers,
            json={"label": "viewer-token"},
        )
        assert resp.status_code == 403, (
            f"Viewer should not create API tokens, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Force-password-change flow
# ---------------------------------------------------------------------------


class TestForcePasswordChange:
    """Admin-created users with force_password_change=True must go through
    a change-token flow before getting a full session."""

    @pytest.mark.asyncio
    async def test_login_force_change_returns_change_token(self, client, factories):
        """Login with force_password_change=True returns requires_change + change_token."""
        user = factories.user(role="viewer", force_password_change=True)
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("requires_change") is True
        assert isinstance(body.get("change_token"), str)
        assert len(body["change_token"]) > 10
        # Must NOT contain full session keys
        assert "token" not in body
        assert "user" not in body

    @pytest.mark.asyncio
    async def test_login_force_change_with_client_hash(self, client, factories):
        """Login via password_hash field also triggers force-change flow."""
        from app.core.security import client_hash_password, hash_password

        temp_pw = "TempPass999!"
        user = factories.user(
            role="viewer",
            hashed_password=hash_password(client_hash_password(temp_pw)),
            force_password_change=True,
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password_hash": client_hash_password(temp_pw)},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("requires_change") is True
        assert isinstance(body.get("change_token"), str)

    @pytest.mark.asyncio
    async def test_force_change_password_completes_login(self, client, factories):
        """Redeeming change_token with a new password returns {token, user}."""
        user = factories.user(role="viewer", force_password_change=True)
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        assert login_resp.status_code == 200
        change_token = login_resp.json()["change_token"]

        resp = await client.post(
            "/api/v1/auth/force-change-password",
            json={"change_token": change_token, "new_password": "NewSecurePassword456!"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "token" in body, f"Expected 'token' key, got: {list(body.keys())}"
        assert "user" in body
        assert body["user"]["email"] == user.email

    @pytest.mark.asyncio
    async def test_force_change_clears_flag(self, client, factories):
        """After completing force-change, next login returns a normal session."""
        user = factories.user(role="viewer", force_password_change=True)
        # Step 1: force-change login
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        change_token = login_resp.json()["change_token"]

        # Step 2: complete the change
        await client.post(
            "/api/v1/auth/force-change-password",
            json={"change_token": change_token, "new_password": "NewSecurePassword456!"},
        )

        # Step 3: login again with new password — should get full session
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "NewSecurePassword456!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body, (
            f"Expected normal login after force-change, got: {list(body.keys())}"
        )
        assert "user" in body
        assert "requires_change" not in body

    @pytest.mark.asyncio
    async def test_force_change_wrong_token_returns_401(self, client):
        """Invalid change_token is rejected with 401."""
        resp = await client.post(
            "/api/v1/auth/force-change-password",
            json={"change_token": "garbage.token.value", "new_password": "Whatever123!"},
        )
        assert resp.status_code == 401
