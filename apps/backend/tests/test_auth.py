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
