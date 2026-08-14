"""P2 hardening: lockout survives the challenge tokens, and health stops leaking build detail.

Login checks the lockout, but the tokens login *hands out* — the force-change
token and the MFA token — did not. A caller holding one could keep redeeming it
while the account was locked, and wrong TOTP codes never fed the counter at all,
so the second factor could be ground down at the rate limiter's pace forever.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytestmark = pytest.mark.asyncio


def _lock(db_session, user, minutes: int = 15):
    from app.core.time import utcnow

    user.locked_until = utcnow() + timedelta(minutes=minutes)
    db_session.flush()


# ── Lockout is enforced where challenge tokens are redeemed ──────────────────


async def test_reject_if_locked_out_is_the_same_generic_401_login_gives(db_session, factories):
    """A distinct message here would turn the lockout into an account oracle."""
    from fastapi import HTTPException

    from app.api.auth import _reject_if_locked_out

    user = factories.user(role="viewer")
    _lock(db_session, user)

    with pytest.raises(HTTPException) as exc:
        _reject_if_locked_out(user)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or password"


async def test_unlocked_and_expired_lock_both_pass(db_session, factories):
    from app.api.auth import _reject_if_locked_out
    from app.core.time import utcnow

    user = factories.user(role="viewer")
    _reject_if_locked_out(user)  # never locked

    user.locked_until = utcnow() - timedelta(minutes=1)  # lock already elapsed
    db_session.flush()
    _reject_if_locked_out(user)


async def test_mfa_verify_refuses_a_locked_account(client, db_session, factories):
    """Holding a valid mfa_token must not outlive the lockout it triggered."""
    import jwt as pyjwt

    from app.services.settings_service import get_or_create_settings

    user = factories.user(role="viewer")
    user.mfa_enabled = True
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db_session.flush()

    cfg = get_or_create_settings(db_session)
    mfa_token = pyjwt.encode(
        {"user_id": user.id, "aud": "cb:mfa-challenge"}, cfg.jwt_secret, algorithm="HS256"
    )

    _lock(db_session, user)

    resp = await client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Invalid email or password"


async def test_failed_mfa_code_increments_the_lockout_counter(client, db_session, factories):
    """Before this, only the rate limiter stood between an attacker and unlimited TOTP guesses."""
    import jwt as pyjwt

    from app.services.settings_service import get_or_create_settings

    user = factories.user(role="viewer")
    user.mfa_enabled = True
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    user.login_attempts = 0
    db_session.flush()

    cfg = get_or_create_settings(db_session)
    mfa_token = pyjwt.encode(
        {"user_id": user.id, "aud": "cb:mfa-challenge"}, cfg.jwt_secret, algorithm="HS256"
    )

    resp = await client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"}
    )
    assert resp.status_code == 401, resp.text

    db_session.refresh(user)
    assert (user.login_attempts or 0) >= 1, "a wrong second factor is a failed login attempt"


# ── Health endpoint disclosure ───────────────────────────────────────────────


async def test_health_hides_build_and_extension_detail_from_anonymous_callers(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()

    assert "version" not in body, "build version is unauthenticated fingerprinting material"
    assert "timescaledb_available" not in body

    # Liveness — what the healthcheck, proxy, and frontend actually poll for.
    assert "state" in body
    assert "ready" in body


async def test_health_still_reports_detail_to_an_authenticated_caller(client, auth_headers):
    resp = await client.get("/api/v1/health", headers=auth_headers)
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert "version" in body
    assert "timescaledb_available" in body
