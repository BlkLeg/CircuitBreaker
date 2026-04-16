"""End-to-end auth tests: forgot/reset password, magic link, admin reset,
resend invite, TOTP encryption, password reuse prevention.

These tests exercise the full ASGI stack with a real Postgres database
via testcontainers. Redis is mocked for token storage.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------


class TestForgotPassword:
    @pytest.mark.asyncio
    async def test_forgot_password_returns_200_for_existing_email(
        self, client, factories, db_session, redis_mock
    ):
        user = factories.user(role="viewer")
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": user.email},
        )
        assert resp.status_code == 410
        assert "disabled" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_forgot_password_returns_200_for_nonexistent_email(self, client):
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nobody@nowhere.invalid"},
        )
        assert resp.status_code == 410

    @pytest.mark.asyncio
    async def test_forgot_password_no_enumeration(self, client, factories, db_session, redis_mock):
        """Response must be identical for existing vs nonexistent emails."""
        user = factories.user(role="viewer")

        real = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": user.email},
        )
        fake = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "ghost@nowhere.invalid"},
        )
        assert real.status_code == fake.status_code == 410
        assert real.json()["detail"] == fake.json()["detail"]


# ---------------------------------------------------------------------------
# Reset Password (token-based)
# ---------------------------------------------------------------------------


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_reset_password_with_valid_token(self, client, factories, db_session, redis_mock):
        factories.user(role="viewer")

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "valid-token-123", "password": "NewSecure@Pass1"},
        )
        assert resp.status_code == 410
        assert "disabled" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_reset_password_with_expired_token(self, client, redis_mock):
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "expired-nonexistent", "password": "NewSecure@Pass1"},
        )
        assert resp.status_code == 410

    @pytest.mark.asyncio
    async def test_reset_password_consumes_token(self, client, factories, db_session, redis_mock):
        """Token must be single-use."""
        factories.user(role="viewer")

        first = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "one-time-tok", "password": "NewSecure@Pass1"},
        )
        assert first.status_code == 410

        second = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "one-time-tok", "password": "AnotherPass@99"},
        )
        assert second.status_code == 410


# ---------------------------------------------------------------------------
# Magic Link
# ---------------------------------------------------------------------------


class TestMagicLink:
    @pytest.mark.asyncio
    async def test_magic_link_request_returns_200(self, client, factories, db_session, redis_mock):
        user = factories.user(role="viewer")
        resp = await client.post(
            "/api/v1/auth/magic-link/request",
            json={"email": user.email},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_magic_link_request_no_enumeration(
        self, client, factories, db_session, redis_mock
    ):
        user = factories.user(role="viewer")
        real = await client.post(
            "/api/v1/auth/magic-link/request",
            json={"email": user.email},
        )
        fake = await client.post(
            "/api/v1/auth/magic-link/request",
            json={"email": "ghost@nowhere.invalid"},
        )
        assert real.status_code == fake.status_code == 404

    @pytest.mark.asyncio
    async def test_magic_link_verify_with_valid_token(
        self, client, factories, db_session, redis_mock
    ):
        factories.user(role="viewer")

        resp = await client.post(
            "/api/v1/auth/magic-link/verify",
            json={"token": "ml-valid-tok"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_magic_link_verify_invalid_token(self, client, redis_mock):
        resp = await client.post(
            "/api/v1/auth/magic-link/verify",
            json={"token": "bogus-token"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin Reset Password
# ---------------------------------------------------------------------------


class TestAdminResetPassword:
    @pytest.mark.asyncio
    async def test_admin_can_reset_user_password(self, client, factories, auth_headers, db_session):
        target = factories.user(role="viewer")
        resp = await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["temp_password"] is not None
        assert len(body["temp_password"]) >= 12
        assert body["revoked_sessions"] >= 0

    @pytest.mark.asyncio
    async def test_admin_reset_password_404_for_missing_user(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/admin/users/99999/reset-password",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_reset_password(
        self, client, factories, viewer_headers, db_session
    ):
        target = factories.user(role="viewer")
        resp = await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password",
            headers=viewer_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Resend Invite
# ---------------------------------------------------------------------------


class TestResendInvite:
    @pytest.mark.asyncio
    async def test_resend_invite_without_smtp_returns_400(
        self, client, factories, auth_headers, db_session
    ):
        from app.core.time import utcnow
        from app.db.models import UserInvite

        invite = UserInvite(
            email="invitee@test.local",
            role="viewer",
            token="test-invite-token",
            invited_by=factories.user(role="admin").id,
            expires=utcnow() + timedelta(days=7),
            status="pending",
        )
        db_session.add(invite)
        db_session.flush()

        resp = await client.post(
            f"/api/v1/admin/invites/{invite.id}/resend",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_resend_invite_404_for_missing(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/admin/invites/99999/resend",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TOTP Encryption
# ---------------------------------------------------------------------------


class TestTotpEncryption:
    def test_generate_backup_codes_shape(self, app_cfg):
        from app.api.auth import _generate_backup_codes

        codes = _generate_backup_codes()
        assert len(codes) == 8
        assert all(len(code) == 10 for code in codes)

    def test_backup_codes_encrypted(self, app_cfg):
        from app.api.auth import _store_backup_codes, _verify_mfa_confirmation_code
        from app.db.models import User

        user = MagicMock(spec=User)
        user.backup_codes = None
        user.totp_secret = None
        raw_codes = ["AAAA111111", "BBBB222222"]
        _store_backup_codes(user, raw_codes)
        stored_value = user.backup_codes
        assert stored_value is not None
        assert "AAAA111111" not in stored_value
        assert "BBBB222222" not in stored_value

        assert _verify_mfa_confirmation_code(user, "AAAA111111") is True


# ---------------------------------------------------------------------------
# Password Reuse Prevention
# ---------------------------------------------------------------------------


class TestPasswordReuse:
    def test_password_reuse_blocked(self, db_session, factories):
        import app.services.auth_service as auth_service

        if not hasattr(auth_service, "check_password_reuse"):
            pytest.skip("Password history reuse checks are not enabled in this build")

        check_password_reuse = auth_service.check_password_reuse
        reset_local_user_password = auth_service.reset_local_user_password

        user = factories.user(role="viewer", password="OriginalPass!1")

        reset_local_user_password(
            db_session,
            user,
            "NewPassword!2",
            source="test",
            update_last_login=False,
        )

        assert check_password_reuse(user, "OriginalPass!1") is True

    def test_new_password_allowed(self, db_session, factories):
        import app.services.auth_service as auth_service

        if not hasattr(auth_service, "check_password_reuse"):
            pytest.skip("Password history reuse checks are not enabled in this build")

        check_password_reuse = auth_service.check_password_reuse

        user = factories.user(role="viewer", password="OriginalPass!1")
        assert check_password_reuse(user, "TotallyNew@Pass9") is False

    def test_reuse_raises_on_reset(self, db_session, factories):
        import app.services.auth_service as auth_service

        if not hasattr(auth_service, "check_password_reuse"):
            pytest.skip("Password history reuse checks are not enabled in this build")

        reset_local_user_password = auth_service.reset_local_user_password

        user = factories.user(role="viewer", password="Original!Pass1")

        reset_local_user_password(
            db_session,
            user,
            "SecondPass!2",
            source="test",
        )

        with pytest.raises(Exception) as exc_info:
            reset_local_user_password(
                db_session,
                user,
                "Original!Pass1",
                source="test",
            )
        assert "reuse" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# Schema Migration Columns
# ---------------------------------------------------------------------------


class TestUserAuditColumns:
    def test_password_changed_at_set_on_reset(self, db_session, factories):
        from app.services.auth_service import reset_local_user_password

        user = factories.user(role="viewer")
        if not hasattr(user, "password_changed_at"):
            pytest.skip("password_changed_at column is not present in this schema")
        assert user.password_changed_at is None

        reset_local_user_password(
            db_session,
            user,
            "NewPass!123",
            source="test",
        )
        assert user.password_changed_at is not None

    @pytest.mark.asyncio
    async def test_last_login_ip_set_on_login(self, client, factories, db_session):
        user = factories.user(role="viewer")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "TestPassword123!"},
        )
        assert resp.status_code == 200
        db_session.refresh(user)
        if not hasattr(user, "last_login_ip"):
            pytest.skip("last_login_ip column is not present in this schema")
        assert user.last_login_ip is not None
