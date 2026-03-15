"""End-to-end auth tests: forgot/reset password, magic link, admin reset,
resend invite, TOTP encryption, password reuse prevention.

These tests exercise the full ASGI stack with a real Postgres database
via testcontainers. Redis is mocked for token storage.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

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

        get_redis_fn, _, _ = redis_mock
        with patch("app.services.password_reset_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user.email},
            )
        assert resp.status_code == 200
        assert "sent" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_forgot_password_returns_200_for_nonexistent_email(self, client):
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "nobody@nowhere.invalid"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_forgot_password_no_enumeration(self, client, factories, db_session, redis_mock):
        """Response must be identical for existing vs nonexistent emails."""
        user = factories.user(role="viewer")

        get_redis_fn, _, _ = redis_mock
        with patch("app.services.password_reset_service.get_redis", new=get_redis_fn):
            real = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": user.email},
            )
        fake = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "ghost@nowhere.invalid"},
        )
        assert real.status_code == fake.status_code == 200
        assert real.json()["detail"] == fake.json()["detail"]


# ---------------------------------------------------------------------------
# Reset Password (token-based)
# ---------------------------------------------------------------------------


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_reset_password_with_valid_token(self, client, factories, db_session, redis_mock):
        user = factories.user(role="viewer")

        get_redis_fn, mock, store = redis_mock
        await mock.setex("password_reset:valid-token-123", 900, str(user.id))

        with patch("app.services.password_reset_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "valid-token-123", "password": "NewSecure@Pass1"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert "user" in body

    @pytest.mark.asyncio
    async def test_reset_password_with_expired_token(self, client, redis_mock):
        get_redis_fn, _, _ = redis_mock

        with patch("app.services.password_reset_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "expired-nonexistent", "password": "NewSecure@Pass1"},
            )
        assert resp.status_code == 400
        assert (
            "expired" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()
        )

    @pytest.mark.asyncio
    async def test_reset_password_consumes_token(self, client, factories, db_session, redis_mock):
        """Token must be single-use."""
        user = factories.user(role="viewer")

        get_redis_fn, mock, store = redis_mock
        await mock.setex("password_reset:one-time-tok", 900, str(user.id))

        with patch("app.services.password_reset_service.get_redis", new=get_redis_fn):
            first = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "one-time-tok", "password": "NewSecure@Pass1"},
            )
            assert first.status_code == 200

            second = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": "one-time-tok", "password": "AnotherPass@99"},
            )
            assert second.status_code == 400


# ---------------------------------------------------------------------------
# Magic Link
# ---------------------------------------------------------------------------


class TestMagicLink:
    @pytest.mark.asyncio
    async def test_magic_link_request_returns_200(self, client, factories, db_session, redis_mock):
        user = factories.user(role="viewer")
        get_redis_fn, _, store = redis_mock
        with patch("app.services.magic_link_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": user.email},
            )
        assert resp.status_code == 200
        # Token must have been stored — proves the magic-link flow ran, not just swallowed
        assert any(k.startswith("magic_link:") for k in store)

    @pytest.mark.asyncio
    async def test_magic_link_request_no_enumeration(
        self, client, factories, db_session, redis_mock
    ):
        user = factories.user(role="viewer")
        get_redis_fn, _, store = redis_mock
        with patch("app.services.magic_link_service.get_redis", new=get_redis_fn):
            real = await client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": user.email},
            )
            fake = await client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": "ghost@nowhere.invalid"},
            )
        assert real.status_code == fake.status_code == 200
        assert real.json()["detail"] == fake.json()["detail"]
        # Only the real user's request should have stored a token
        assert any(k.startswith("magic_link:") for k in store)

    @pytest.mark.asyncio
    async def test_magic_link_verify_with_valid_token(
        self, client, factories, db_session, redis_mock
    ):
        user = factories.user(role="viewer")

        get_redis_fn, mock, store = redis_mock
        await mock.setex("magic_link:ml-valid-tok", 600, str(user.id))

        with patch("app.services.magic_link_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/magic-link/verify",
                json={"token": "ml-valid-tok"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert "user" in body

    @pytest.mark.asyncio
    async def test_magic_link_verify_invalid_token(self, client, redis_mock):
        get_redis_fn, _, _ = redis_mock

        with patch("app.services.magic_link_service.get_redis", new=get_redis_fn):
            resp = await client.post(
                "/api/v1/auth/magic-link/verify",
                json={"token": "bogus-token"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Admin Reset Password
# ---------------------------------------------------------------------------


class TestAdminResetPassword:
    @pytest.mark.asyncio
    async def test_admin_can_reset_user_password(self, client, factories, auth_headers, db_session):
        target = factories.user(role="viewer")
        resp = await client.post(
            f"/api/v1/admin/users/{target.id}/reset-password",
            json={"send_email": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["force_password_change"] is True
        assert body["temporary_password"] is not None
        assert len(body["temporary_password"]) >= 16

    @pytest.mark.asyncio
    async def test_admin_reset_password_404_for_missing_user(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/admin/users/99999/reset-password",
            json={"send_email": False},
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
            json={"send_email": False},
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
        assert resp.status_code == 400
        assert "smtp" in resp.json()["detail"].lower()

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
    def test_encrypt_decrypt_round_trip(self, app_cfg):
        from app.api.auth import _decrypt_totp_secret, _encrypt_totp_secret

        secret = "JBSWY3DPEHPK3PXP"
        encrypted = _encrypt_totp_secret(secret)
        assert encrypted != secret
        assert encrypted.startswith("gAAAAA")
        decrypted = _decrypt_totp_secret(encrypted)
        assert decrypted == secret

    def test_decrypt_plaintext_passthrough(self, app_cfg):
        from app.api.auth import _decrypt_totp_secret

        plain = "JBSWY3DPEHPK3PXP"
        assert _decrypt_totp_secret(plain) == plain

    def test_backup_codes_encrypted(self, app_cfg):
        from app.api.auth import _load_backup_codes, _store_backup_codes
        from app.db.models import User

        user = MagicMock(spec=User)
        user.backup_codes = None
        raw_codes = ["AAAA111111", "BBBB222222"]
        _store_backup_codes(user, raw_codes)
        stored_value = user.backup_codes
        assert stored_value is not None
        assert stored_value.startswith("gAAAAA")

        loaded = _load_backup_codes(user)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Password Reuse Prevention
# ---------------------------------------------------------------------------


class TestPasswordReuse:
    def test_password_reuse_blocked(self, db_session, factories):
        from app.services.auth_service import check_password_reuse, reset_local_user_password

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
        from app.services.auth_service import check_password_reuse

        user = factories.user(role="viewer", password="OriginalPass!1")
        assert check_password_reuse(user, "TotallyNew@Pass9") is False

    def test_reuse_raises_on_reset(self, db_session, factories):
        from app.services.auth_service import reset_local_user_password

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
        assert user.last_login_ip is not None
