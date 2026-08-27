"""OAuth sign-in decided who you are from the email alone.

`_upsert_oauth_user` looked a user up by email and, on a hit, assigned
`user.provider = provider`. Any provider account carrying an existing user's address was
therefore that user: register a GitHub account under an admin's work address, sign in,
and the local-password admin row is rebound to you. It also ignored `registration_open`,
so closing registration closed only the form, and never normalised the address, so
"Ops@Corp" and "ops@corp" were two accounts.

`_issue_jwt_and_redirect` issued a full session without consulting `mfa_enabled`, so
enrolling in MFA protected the password path and nothing else.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi import HTTPException

from app.api.auth_oauth import _upsert_oauth_user


def _settings(db):
    from app.services.settings_service import get_or_create_settings

    return get_or_create_settings(db)


def test_a_local_account_is_not_rebound_to_a_provider(db_session, factories):
    """The takeover, stated directly."""
    victim = factories.user(role="admin", email="ops@corp.example", provider="local")
    db_session.commit()
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _upsert_oauth_user(
            db_session, "ops@corp.example", "Attacker", "github", {"access_token": "x"}
        )

    assert exc.value.status_code == 403
    db_session.expire_all()
    assert db_session.get(type(victim), victim.id).provider == "local", (
        "the local account was rebound to the OAuth provider"
    )


def test_the_same_provider_signing_in_again_still_works(db_session, factories):
    """The gate must not have been tightened into a wall: this is the ordinary path."""
    user = factories.user(role="viewer", email="dev@corp.example", provider="github")
    db_session.commit()
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    db_session.commit()

    got, is_new = _upsert_oauth_user(
        db_session, "dev@corp.example", "Dev", "github", {"access_token": "x"}
    )

    assert is_new is False
    assert got.id == user.id


def test_an_invite_may_still_link_an_existing_address(db_session, factories):
    """An invite is an administrator stating this address may hold an account."""
    user = factories.user(role="viewer", email="new@corp.example", provider="local")
    db_session.commit()
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    db_session.commit()

    got, _ = _upsert_oauth_user(
        db_session, "new@corp.example", "New", "google", {"access_token": "x"}, invited=True
    )

    assert got.id == user.id
    assert got.provider == "google"


def test_creation_honours_registration_open(db_session):
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    cfg.registration_open = False
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _upsert_oauth_user(
            db_session, "stranger@corp.example", "Stranger", "github", {"access_token": "x"}
        )

    assert exc.value.status_code == 403


def test_an_invited_signup_is_allowed_while_registration_is_closed(db_session):
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    cfg.registration_open = False
    db_session.commit()

    got, is_new = _upsert_oauth_user(
        db_session,
        "invited@corp.example",
        "Invited",
        "github",
        {"access_token": "x"},
        invited=True,
    )

    assert is_new is True
    assert got.email == "invited@corp.example"


def test_the_address_is_normalised_before_lookup(db_session, factories):
    """Otherwise the provider's spelling decides which account a sign-in reaches."""
    user = factories.user(role="viewer", email="mixed@corp.example", provider="github")
    db_session.commit()
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    db_session.commit()

    got, is_new = _upsert_oauth_user(
        db_session, "  Mixed@Corp.Example  ", "Mixed", "github", {"access_token": "x"}
    )

    assert is_new is False, "a differently-cased address created a second account"
    assert got.id == user.id


async def test_oauth_sign_in_demands_the_second_factor_when_mfa_is_enabled(
    db_session, factories, monkeypatch
):
    """OAuth used to hand out a full session regardless of mfa_enabled."""
    from starlette.requests import Request

    from app.api.auth_oauth import _issue_jwt_and_redirect

    user = factories.user(role="admin", email="mfa@corp.example", provider="github")
    user.mfa_enabled = True
    cfg = _settings(db_session)
    cfg.auth_enabled = True
    db_session.commit()

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    resp = await _issue_jwt_and_redirect(user, "https://cb.example", db_session, request)

    location = resp.headers["location"]
    assert "cb_auth_code=" not in location, "a session was issued without the second factor"
    assert "cb_mfa_token=" in location
    assert "set-cookie" not in {k.lower() for k in resp.headers}, "a session cookie was set"

    challenge = location.split("cb_mfa_token=", 1)[1]
    claims = jwt.decode(
        challenge, cfg.jwt_secret, algorithms=["HS256"], audience="cb:mfa-challenge"
    )
    assert claims["user_id"] == user.id
