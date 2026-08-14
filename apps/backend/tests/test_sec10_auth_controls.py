from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from starlette.requests import Request

from app.core.time import utcnow


def _request(client_host: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_host, 54321),
            "scheme": "http",
        }
    )


class TestSEC10LockoutOrdering:
    @pytest.mark.asyncio
    async def test_locked_user_cannot_receive_force_change_token(
        self, client, factories, db_session
    ):
        user = factories.user(
            role="viewer",
            password="RotateMe123!",
            force_password_change=True,
            locked_until=utcnow() + timedelta(minutes=15),
            login_attempts=5,
        )
        db_session.commit()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "RotateMe123!"},
        )

        assert resp.status_code == 401
        assert "change_token" not in resp.text
        db_session.refresh(user)
        assert user.force_password_change is True
        assert user.login_attempts == 5
        assert user.locked_until is not None

    @pytest.mark.asyncio
    async def test_locked_user_cannot_receive_mfa_challenge(self, client, factories, db_session):
        secret = pyotp.random_base32()
        user = factories.user(
            role="viewer",
            password="MfaLocked123!",
            mfa_enabled=True,
            totp_secret=secret,
            locked_until=utcnow() + timedelta(minutes=15),
            login_attempts=5,
        )
        db_session.commit()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "MfaLocked123!"},
        )

        assert resp.status_code == 401
        assert "mfa_token" not in resp.text
        db_session.refresh(user)
        assert user.mfa_enabled is True
        assert user.login_attempts == 5
        assert user.locked_until is not None


class TestSEC10ChallengeTokens:
    @pytest.mark.asyncio
    async def test_force_change_token_is_not_a_session_token(self, client, factories):
        user = factories.user(
            role="viewer",
            password="MustChange123!",
            force_password_change=True,
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "MustChange123!"},
        )

        assert login.status_code == 200
        change_token = login.json()["change_token"]
        protected = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": f"Bearer {change_token}"},
        )
        assert protected.status_code == 401

    @pytest.mark.asyncio
    async def test_mfa_token_is_not_a_session_token(self, client, factories):
        user = factories.user(
            role="viewer",
            password="MfaToken123!",
            mfa_enabled=True,
            totp_secret=pyotp.random_base32(),
        )

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "MfaToken123!"},
        )

        assert login.status_code == 200
        mfa_token = login.json()["mfa_token"]
        protected = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": f"Bearer {mfa_token}"},
        )
        assert protected.status_code == 401


class TestSEC10MfaBackupCodes:
    @pytest.mark.asyncio
    async def test_backup_code_login_is_single_use(self, client, factories, db_session):
        from app.api.auth import _store_backup_codes

        user = factories.user(
            role="viewer",
            password="BackupMfa123!",
            mfa_enabled=True,
            totp_secret=pyotp.random_base32(),
        )
        _store_backup_codes(user, ["ABCD123456"])
        db_session.commit()

        first_login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "BackupMfa123!"},
        )
        assert first_login.status_code == 200
        first_verify = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": first_login.json()["mfa_token"], "code": "ABCD123456"},
        )
        assert first_verify.status_code == 200
        assert "token" in first_verify.json()
        db_session.refresh(user)
        assert "ABCD123456" not in (user.backup_codes or "")
        assert json.loads(user.backup_codes or "[]") == []

        second_login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "BackupMfa123!"},
        )
        assert second_login.status_code == 200
        second_verify = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": second_login.json()["mfa_token"], "code": "ABCD123456"},
        )
        assert second_verify.status_code == 401


class TestSEC10OAuthCallbackState:
    def test_oauth_state_is_single_use(self, db_session):
        from fastapi import HTTPException

        from app.api.auth_oauth import _INVALID_STATE, _pop_state_or_400
        from app.db.models import OAuthState

        state = OAuthState(
            state="single-use-state",
            provider="github",
            created_at=datetime.now(UTC).isoformat(),
        )
        db_session.add(state)
        db_session.commit()

        first = _pop_state_or_400(db_session, "single-use-state", OAuthState.provider == "github")
        assert first.state == "single-use-state"

        with pytest.raises(HTTPException) as exc_info:
            _pop_state_or_400(db_session, "single-use-state", OAuthState.provider == "github")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == _INVALID_STATE

    def test_expired_oauth_state_is_consumed(self, db_session):
        from fastapi import HTTPException

        from app.api.auth_oauth import _STATE_EXPIRED, _pop_state_or_400
        from app.db.models import OAuthState

        db_session.add(
            OAuthState(
                state="expired-state",
                provider="github",
                created_at=(datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
            )
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _pop_state_or_400(db_session, "expired-state", OAuthState.provider == "github")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == _STATE_EXPIRED

        with pytest.raises(HTTPException):
            _pop_state_or_400(db_session, "expired-state", OAuthState.provider == "github")

    @pytest.mark.asyncio
    async def test_oidc_authorize_persists_nonce_and_pkce_verifier(
        self, client, db_session, monkeypatch
    ):
        from httpx import Request as HttpxRequest
        from httpx import Response

        from app.db.models import AppSettings, OAuthState

        cfg = {
            "enabled": True,
            "type": "oidc",
            "slug": "corp",
            "name": "corp",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
        }
        settings = db_session.get(AppSettings, 1)
        settings.oidc_providers = [cfg]
        db_session.commit()
        monkeypatch.setattr("app.api.auth_oauth._validate_oidc_url", lambda url, label: None)

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, **kwargs):
                assert url == cfg["discovery_url"]
                return Response(
                    200,
                    request=HttpxRequest("GET", url),
                    json={
                        "authorization_endpoint": "https://idp.example.com/auth",
                        "token_endpoint": "https://idp.example.com/token",
                        "userinfo_endpoint": "https://idp.example.com/userinfo",
                        "issuer": "https://idp.example.com",
                        "jwks_uri": "https://idp.example.com/jwks",
                    },
                )

        monkeypatch.setattr("app.api.auth_oauth.httpx.AsyncClient", FakeAsyncClient)

        resp = await client.get("/api/v1/auth/oauth/oidc/corp", follow_redirects=False)

        assert resp.status_code == 302, resp.text
        location = resp.headers["location"]
        query = parse_qs(urlparse(location).query)
        state = query["state"][0]
        nonce = query["nonce"][0]
        assert query["code_challenge_method"] == ["S256"]
        stored = db_session.query(OAuthState).filter_by(state=state).one()
        assert stored.nonce == nonce
        assert stored.provider.startswith("oidc:corp:")
        assert len(stored.provider.split(":", 2)[2]) >= 32


class TestSEC10TrustedProxyIdentity:
    def test_untrusted_peer_cannot_spoof_forwarded_for(self, monkeypatch):
        from app.core import forwarded, rate_limit

        monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.0.0.0/8"])
        monkeypatch.setattr(forwarded, "_trusted_proxy_cache", None)

        identity = rate_limit.trusted_client_identity(_request("203.0.113.10", "198.51.100.44"))

        assert identity == "203.0.113.10"

    def test_trusted_proxy_uses_nearest_untrusted_forwarded_hop(self, monkeypatch):
        """The rightmost hop outside the trusted CIDRs wins.

        The shipped nginx appends to X-Forwarded-For, so entries further left
        may have been supplied by the caller itself.
        """
        from app.core import forwarded, rate_limit

        monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.0.0.0/8"])
        monkeypatch.setattr(forwarded, "_trusted_proxy_cache", None)

        identity = rate_limit.trusted_client_identity(
            _request("10.1.2.3", "198.51.100.44, 198.51.100.45")
        )

        assert identity == "198.51.100.45"
