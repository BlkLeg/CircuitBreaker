"""Phase 6.5: User management — invite, lockout, sessions, RBAC."""

import pytest

from app.core.time import utcnow_iso
from app.db.models import User
from app.services.settings_service import get_or_create_settings
from app.services.user_service import (
    accept_invite,
    create_invite,
    record_failed_login,
    revoke_invite,
    unlock_user,
)


def _create_admin(db):
    """Create an admin user."""
    from app.core.security import gravatar_hash, hash_password

    now = utcnow_iso()
    u = User(
        email="admin@example.com",
        hashed_password=hash_password("Admin1234!"),
        gravatar_hash=gravatar_hash("admin@example.com"),
        display_name="Admin",
        language="en",
        is_admin=True,
        is_superuser=True,
        is_active=True,
        created_at=now,
        role="admin",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create_user(db, email="user@example.com", role="viewer"):
    """Create a user."""
    from app.core.security import gravatar_hash, hash_password

    now = utcnow_iso()
    u = User(
        email=email,
        hashed_password=hash_password("User1234!"),
        gravatar_hash=gravatar_hash(email),
        display_name=email.split("@")[0],
        language="en",
        is_admin=(role == "admin"),
        is_superuser=(role == "admin"),
        is_active=True,
        created_at=now,
        role=role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_invite_workflow(db):
    """Admin creates invite, user accepts, role confirmed."""

    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        cfg.jwt_secret = "test-secret"
        db.commit()

    admin = _create_admin(db)
    invite, token = create_invite(db, admin, "newuser@example.com", "editor")
    assert invite.id
    assert invite.status == "pending"
    assert invite.role == "editor"

    user = accept_invite(db, token, "NewPass1234!", "New User")
    assert user.email == "newuser@example.com"
    assert user.role == "editor"
    assert user.invited_by == admin.id

    db.refresh(invite)
    assert invite.status == "accepted"


def test_login_lockout(db):
    """5 failed logins lock the account."""
    cfg = get_or_create_settings(db)
    cfg.login_lockout_attempts = 3
    cfg.login_lockout_minutes = 15
    db.commit()

    user = _create_user(db)
    assert user.locked_until is None

    record_failed_login(db, user, cfg)
    db.refresh(user)
    assert user.login_attempts == 1
    assert user.locked_until is None

    record_failed_login(db, user, cfg)
    record_failed_login(db, user, cfg)
    db.refresh(user)
    assert user.login_attempts == 3
    assert user.locked_until is not None


def test_admin_unlock(db):
    """Admin unlocks user."""
    from datetime import timedelta

    from app.core.time import utcnow

    user = _create_user(db)
    user.login_attempts = 5
    user.locked_until = utcnow() + timedelta(minutes=15)
    db.commit()

    unlocked = unlock_user(db, user.id)
    assert unlocked
    assert unlocked.login_attempts == 0
    assert unlocked.locked_until is None


def test_revoke_invite(db):
    """Revoke invite works."""
    cfg = get_or_create_settings(db)
    if not cfg.jwt_secret:
        cfg.jwt_secret = "test-secret"
        db.commit()

    admin = _create_admin(db)
    invite, _ = create_invite(db, admin, "rev@example.com", "viewer")
    assert invite.status == "pending"

    ok = revoke_invite(db, invite.id)
    assert ok
    db.refresh(invite)
    assert invite.status == "revoked"


def test_invite_accept_invalid_token(db):
    """Accept invalid token raises."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        accept_invite(db, "invalid-token", "Pass1234!")
    assert exc.value.status_code == 400


def test_admin_users_list(client, auth_headers):
    """Admin can list users."""
    r = client.get("/api/v1/admin/users", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    u = next((x for x in data if x["email"] == "test@example.com"), None)
    assert u
    assert "role" in u


def test_admin_users_create(client, auth_headers):
    """Admin can create user."""
    r = client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "created@example.com",
            "password": "Created1234!",
            "role": "editor",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "created@example.com"
    assert data["role"] == "editor"


def test_admin_invite_create(client, auth_headers):
    """Admin can create invite."""
    r = client.post(
        "/api/v1/admin/invites",
        headers=auth_headers,
        json={"email": "invited@example.com", "role": "viewer"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert "invite_url" in data
    assert data["invite_url"].find("token=") >= 0


def test_admin_invite_email_uses_external_app_url(client, auth_headers, monkeypatch):
    from app.services.smtp_service import SmtpService

    captured = {}

    async def _capture_send_invite(self, to_email, token, invited_by, base_url):
        captured["to_email"] = to_email
        captured["token"] = token
        captured["invited_by"] = invited_by
        captured["base_url"] = base_url

    monkeypatch.setattr(SmtpService, "send_invite", _capture_send_invite)

    client.put(
        "/api/v1/settings",
        headers=auth_headers,
        json={
            "api_base_url": "https://circuitbreaker.example.com",
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_from_email": "noreply@example.com",
            "smtp_from_name": "Circuit Breaker",
        },
    )

    r = client.post(
        "/api/v1/admin/invites",
        headers=auth_headers,
        json={"email": "external@example.com", "role": "viewer"},
    )
    assert r.status_code == 200
    assert captured["to_email"] == "external@example.com"
    assert captured["base_url"] == "https://circuitbreaker.example.com"


def test_accept_invite_creates_user(client, auth_headers):
    """Accept invite creates user and returns token."""
    # Create invite
    inv_resp = client.post(
        "/api/v1/admin/invites",
        headers=auth_headers,
        json={"email": "accepted@example.com", "role": "editor"},
    )
    assert inv_resp.status_code == 200
    token = inv_resp.json()["token"]

    # Accept (no auth required)
    r = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": token, "password": "Accepted1234!"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["user"]["email"] == "accepted@example.com"
    assert data["user"]["role"] == "editor"
