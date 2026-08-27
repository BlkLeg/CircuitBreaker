"""B28 — every auth_service path that hands out a full-length session token must
record a UserSession row.

Revocation in this codebase is *table-driven*: `is_session_revoked` (called from
`core.security.resolve_user_id` on every authenticated request) looks the raw JWT
up by SHA-256 hash in `user_sessions`, and `revoke_all_sessions` /
`revoke_token_session` flip the `revoked` flag on rows in that same table. A token
that was never written to `user_sessions` therefore cannot be revoked by any code
path we ship — the admin "reset password" button reports 0 sessions killed and the
token keeps working until it expires on its own.

These tests assert on the revocation primitives themselves, not on the presence of
a call site, so they stay honest if the recording is ever moved or refactored.
"""

import pytest

from app.services.auth_service import register
from app.services.settings_service import get_or_create_settings
from app.services.user_service import is_session_revoked, revoke_all_sessions


@pytest.fixture
def cfg(db_session, app_cfg):
    return get_or_create_settings(db_session)


def test_register_issued_token_is_revocable(db_session, factories, cfg):
    """A token minted by register() must be findable by the revocation path."""
    # register() refuses to run against an empty user table (bootstrap guard), so
    # seed one unrelated account first.
    factories.user(role="viewer")

    result = register(
        db_session,
        "b28-register@example.com",
        "RegisterPassword123!",
        cfg,
        display_name="B28 Register",
    )

    from app.db.models import User

    user = db_session.query(User).filter(User.email == "b28-register@example.com").one()

    revoked = revoke_all_sessions(db_session, user.id)
    assert revoked == 1, (
        "revoke_all_sessions found no session for the freshly registered user — "
        "register() handed out a token it never recorded in user_sessions"
    )
    assert is_session_revoked(db_session, result.token) is True, (
        "the register-issued token survived revoke_all_sessions"
    )
