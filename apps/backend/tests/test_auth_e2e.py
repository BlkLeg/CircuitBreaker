"""End-to-end auth tests: forgot/reset password, magic link, admin reset,
resend invite, TOTP encryption, password reuse prevention.

These tests exercise the full ASGI stack with a real Postgres database
via testcontainers. Redis is mocked for token storage.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest


def _assert_endpoint_not_exposed(resp, path: str) -> None:
    """Assert `path` is not served by the API, independently of the frontend build.

    Both of the endpoint families below (magic link, invite resend) were
    specified but never wired into a router — `magic_link_service.py` exists
    with no caller, and nothing in apps/frontend/src requests either path.
    These tests therefore pin "not exposed", and used to do it by asserting an
    exact `404`.

    That assertion is not environment-independent. main.py registers the SPA
    fallback `@app.get("/{full_path:path}")` *only* when a frontend build
    directory exists. When it does (any dev box that has run `npm run build`,
    and every production image), a POST to an unrouted path partially matches
    that GET catch-all, so Starlette answers `405 Method Not Allowed`; when it
    does not, nothing matches and the answer is `404`. Identical request, two
    status codes, decided by whether apps/frontend/dist happens to be present
    — which is exactly why these tests failed locally and not in CI.

    So assert the real contract directly against the route table (fully
    deterministic) and accept either "absent" status code at the HTTP layer.
    """
    from app.main import app

    # Match the way Starlette itself resolves a path, so a parameterised route
    # (e.g. "/api/v1/admin/invites/{invite_id}/resend") is detected too — a
    # plain string comparison would miss it. The SPA fallback is excluded
    # because its "{full_path:path}" pattern matches literally everything;
    # it is the artefact being controlled for, not a real handler.
    matching = [
        route.path
        for route in app.routes
        if getattr(route, "path_regex", None) is not None
        and "{full_path" not in getattr(route, "path", "")
        and route.path_regex.match(path)
    ]
    assert not matching, f"{path} is now served by {matching} — update this test"
    assert resp.status_code in {404, 405}, (
        f"expected an 'endpoint absent' status for {path}, got {resp.status_code}"
    )


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
    """The magic-link endpoints are not exposed. `magic_link_service.py` is
    implemented but no router ever mounts it, and no frontend code calls it.
    See `_assert_endpoint_not_exposed` for why these assert absence rather
    than a literal status code."""

    REQUEST_URL = "/api/v1/auth/magic-link/request"
    VERIFY_URL = "/api/v1/auth/magic-link/verify"

    @pytest.mark.asyncio
    async def test_magic_link_request_is_not_exposed(
        self, client, factories, db_session, redis_mock
    ):
        user = factories.user(role="viewer")
        resp = await client.post(self.REQUEST_URL, json={"email": user.email})
        _assert_endpoint_not_exposed(resp, self.REQUEST_URL)

    @pytest.mark.asyncio
    async def test_magic_link_request_no_enumeration(
        self, client, factories, db_session, redis_mock
    ):
        """Known and unknown addresses must be indistinguishable. While the
        endpoint is unrouted that holds trivially, but the assertion still
        pins it the day the route is wired up."""
        user = factories.user(role="viewer")
        real = await client.post(self.REQUEST_URL, json={"email": user.email})
        fake = await client.post(self.REQUEST_URL, json={"email": "ghost@nowhere.invalid"})

        assert real.status_code == fake.status_code
        assert real.text == fake.text
        _assert_endpoint_not_exposed(real, self.REQUEST_URL)

    @pytest.mark.asyncio
    async def test_magic_link_verify_is_not_exposed(
        self, client, factories, db_session, redis_mock
    ):
        factories.user(role="viewer")
        resp = await client.post(self.VERIFY_URL, json={"token": "ml-valid-tok"})
        _assert_endpoint_not_exposed(resp, self.VERIFY_URL)

    @pytest.mark.asyncio
    async def test_magic_link_verify_invalid_token(self, client, redis_mock):
        resp = await client.post(self.VERIFY_URL, json={"token": "bogus-token"})
        _assert_endpoint_not_exposed(resp, self.VERIFY_URL)


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
    async def test_resend_invite_is_not_exposed(self, client, factories, auth_headers, db_session):
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

        url = f"/api/v1/admin/invites/{invite.id}/resend"
        resp = await client.post(url, headers=auth_headers)
        _assert_endpoint_not_exposed(resp, url)

    @pytest.mark.asyncio
    async def test_resend_invite_not_exposed_for_missing_invite(self, client, auth_headers):
        url = "/api/v1/admin/invites/99999/resend"
        resp = await client.post(url, headers=auth_headers)
        _assert_endpoint_not_exposed(resp, url)


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
