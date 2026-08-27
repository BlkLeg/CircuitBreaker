"""B28 — every HTTP path that hands a caller a full-length session token must
leave behind a revocable `user_sessions` row.

Revocation in this codebase is *table-driven*. `is_session_revoked()` — called
from `core.security.resolve_optional_user_id_sync` on every authenticated
request — looks the raw JWT up by SHA-256 hash in `user_sessions`;
`revoke_all_sessions()` (admin reset-password, admin "revoke sessions") and
`revoke_token_session()` (logout) flip the `revoked` flag on rows in that same
table. A token that was never written there is *unkillable*: it keeps
authenticating until `session_timeout_hours` elapses on its own, and the admin
UI reports "0 sessions revoked" while it does.

The two password paths that used to mint such a token were `POST
/api/v1/auth/register` and `POST /api/v1/auth/accept-invite`. These tests
deliberately drive the **HTTP endpoints**, not the service functions: the
accept-invite half of B28 survived a first round of fixing precisely because
the only regression test called `auth_service.register()` directly, and the
remaining unrecorded `_make_token(...)` call lived one layer up in
`api/auth.py`. Service-level coverage cannot see that.

Every assertion below is on the real revocation primitives (the count returned
by `revoke_all_sessions`, `is_session_revoked`, and a real 401 from a protected
endpoint) — never on the presence of a `record_session` call site — so they stay
honest if the recording is ever moved or refactored. Do not relax
`revoked == 1` to `>= 0` or drop the follow-up 401: a session count assertion
that cannot fail is exactly the hole B28 hid in.
"""

import pytest

from app.db.models import User
from app.services.user_service import (
    create_invite,
    is_session_revoked,
    revoke_all_sessions,
)

REGISTER_URL = "/api/v1/auth/register"
ACCEPT_INVITE_URL = "/api/v1/auth/accept-invite"
ME_URL = "/api/v1/auth/me"

TEST_PASSWORD = "B28SessionPassword123!"


def _user_by_email(db_session, email: str) -> User:
    return db_session.query(User).filter(User.email == email.lower()).one()


def _resynced(client, headers: dict[str, str]) -> dict[str, str]:
    """Re-point CSRF at whatever cookie the shared client is currently holding.

    `middleware/csrf.py` is a plain double-submit check: it compares the
    `X-CSRF-Token` header against the `cb_csrf` cookie and nothing else. The
    `auth_headers` fixture captured its header when the admin logged in, but
    these tests drive `/auth/accept-invite` on the *same* client first, and that
    response sets a fresh `cb_csrf` for the newly created user — overwriting the
    admin's in the shared cookie jar. The admin's stale header then fails
    against the invitee's cookie with 403 "CSRF token invalid", which looks like
    an authorization failure and is really a fixture-ordering artefact.

    The header the caller passes stays authoritative for `Authorization`; only
    the CSRF pair is made self-consistent, which is all the middleware checks.
    """
    csrf = client.cookies.get("cb_csrf")
    return headers if csrf is None else {**headers, "X-CSRF-Token": csrf}


async def _assert_token_is_dead(client, db_session, user: User, token: str, path: str) -> None:
    """The shared half of both tests: prove the shipped revocation code kills it.

    `revoke_all_sessions` returning 1 is the load-bearing assertion — it is the
    exact number the admin reset-password response reports, and it is 0 for a
    token that was never recorded.
    """
    revoked = revoke_all_sessions(db_session, user.id)
    assert revoked == 1, (
        f"revoke_all_sessions() found no session for the user created via {path} — "
        f"that path handed out a token it never recorded in user_sessions, so "
        f"logout, admin reset-password and admin revoke-sessions all miss it"
    )
    assert is_session_revoked(db_session, token) is True, (
        f"the token issued by {path} survived revoke_all_sessions()"
    )

    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, (
        f"the token issued by {path} still authenticates after every session for "
        f"its user was revoked (got HTTP {resp.status_code})"
    )


@pytest.mark.asyncio
async def test_register_endpoint_issued_token_is_revocable(client, db_session, factories, app_cfg):
    """POST /auth/register must produce a session the revocation code can kill."""
    # register() refuses to run against an empty user table (bootstrap guard),
    # and the endpoint is gated on AppSettings.registration_open.
    factories.user(role="viewer")
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db_session)
    cfg.registration_open = True
    db_session.flush()

    email = "b28-register-endpoint@example.com"
    resp = await client.post(
        REGISTER_URL,
        json={"email": email, "password": TEST_PASSWORD, "display_name": "B28 Register"},
    )
    assert resp.status_code == 200, f"register failed: {resp.status_code} {resp.text}"
    token = resp.json()["token"]

    await _assert_token_is_dead(
        client, db_session, _user_by_email(db_session, email), token, REGISTER_URL
    )


@pytest.mark.asyncio
async def test_accept_invite_endpoint_issued_token_is_revocable(
    client, db_session, factories, app_cfg
):
    """POST /auth/accept-invite must produce a session the revocation code can kill.

    Invites are the normal way a second user joins an instance — /auth/register
    is gated behind AppSettings.registration_open — so this is the larger half
    of B28 in practice, and until this test existed nothing in the suite
    exercised accept-invite at all.
    """
    admin = factories.user(role="admin")
    email = "b28-invite-endpoint@example.com"
    _invite, invite_token = create_invite(db_session, admin, email, "viewer")

    resp = await client.post(
        ACCEPT_INVITE_URL,
        json={"token": invite_token, "password": TEST_PASSWORD, "display_name": "B28 Invite"},
    )
    assert resp.status_code == 200, f"accept-invite failed: {resp.status_code} {resp.text}"
    token = resp.json()["token"]

    await _assert_token_is_dead(
        client, db_session, _user_by_email(db_session, email), token, ACCEPT_INVITE_URL
    )


@pytest.mark.asyncio
async def test_admin_reset_password_reports_and_kills_the_invite_session(
    client, db_session, factories, auth_headers, app_cfg
):
    """The operator-visible half: the admin reset-password button must report a
    non-zero count and the invited user's token must stop working.

    This is the assertion tests/test_auth_e2e.py's `revoked_sessions >= 0` could
    never make. `== 1` is the honest value here — exactly one session was issued
    by accept-invite — and it drops to 0 the moment accept-invite stops
    recording.
    """
    admin = factories.user(role="admin")
    email = "b28-invite-reset@example.com"
    _invite, invite_token = create_invite(db_session, admin, email, "viewer")

    accepted = await client.post(
        ACCEPT_INVITE_URL,
        json={"token": invite_token, "password": TEST_PASSWORD},
    )
    assert accepted.status_code == 200, f"accept-invite failed: {accepted.text}"
    session_token = accepted.json()["token"]
    invited = _user_by_email(db_session, email)

    resp = await client.post(
        f"/api/v1/admin/users/{invited.id}/reset-password",
        headers=_resynced(client, auth_headers),
    )
    assert resp.status_code == 200, f"reset-password failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["revoked_sessions"] == 1, (
        "admin reset-password reported "
        f"{body['revoked_sessions']} revoked sessions for a user whose only "
        "session came from accept-invite — the invite-issued token was never "
        "recorded, so the admin was told nothing needed killing"
    )

    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {session_token}"})
    assert me.status_code == 401, (
        "the invite-issued token still authenticates after the admin reset the "
        f"user's password (got HTTP {me.status_code})"
    )
