"""
Auth system tests — covers gaps F3-1 through F3-7.

Uses the existing ``client`` / ``db`` fixtures from conftest.py (in-memory SQLite).
"""

import pytest

DEFAULT_TEST_EMAIL = "test@example.com"
DEFAULT_TEST_PASSWORD = "Secure1234!"
BOOTSTRAP_TEST_PASSWORD = DEFAULT_TEST_PASSWORD
INVALID_SHORT_PASSWORD = "short"
INVALID_WRONG_PASSWORD = "wrongpassword"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enable_auth(client):
    """Enable auth via settings and return the settings payload."""
    resp = client.put("/api/v1/settings", json={"auth_enabled": True})
    return resp.json()


def _register(client, email=DEFAULT_TEST_EMAIL, password=DEFAULT_TEST_PASSWORD, display_name=None):
    status = client.get("/api/v1/bootstrap/status")
    if status.status_code == 200 and status.json().get("needs_bootstrap"):
        body = {
            "email": email,
            "password": password,
            "theme_preset": "one-dark",
        }
        if display_name:
            body["display_name"] = display_name
        return client.post("/api/v1/bootstrap/initialize", json=body)

    body = {"email": email, "password": password}
    if display_name:
        body["display_name"] = display_name
    return client.post("/api/v1/auth/register", json=body)


def _login(client, email=DEFAULT_TEST_EMAIL, password=DEFAULT_TEST_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_bootstrap_status_on_fresh_db(client):
    resp = client.get("/api/v1/bootstrap/status")
    assert resp.status_code == 200
    assert resp.json()["needs_bootstrap"] is True
    assert resp.json()["user_count"] == 0


def test_bootstrap_initialize_creates_admin_and_enables_auth(client):
    resp = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "bootstrap@example.com",
            "password": BOOTSTRAP_TEST_PASSWORD,
            "theme_preset": "one-dark",
            "display_name": "Bootstrap Admin",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"]
    assert data["user"]["is_admin"] is True
    assert data["theme"]["preset"] == "one-dark"

    settings_resp = client.get("/api/v1/settings")
    assert settings_resp.status_code == 200
    assert settings_resp.json()["auth_enabled"] is True


def test_bootstrap_initialize_conflicts_after_first_user(client):
    first = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "first@example.com",
            "password": BOOTSTRAP_TEST_PASSWORD,
            "theme_preset": "one-dark",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "second@example.com",
            "password": BOOTSTRAP_TEST_PASSWORD,
            "theme_preset": "dark-matter",
        },
    )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# F3-1  jwt_secret must NOT be exposed in GET /settings
# ---------------------------------------------------------------------------

def test_settings_jwt_secret_hidden(client):
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "jwt_secret" not in data, "jwt_secret should never appear in the settings response"


# ---------------------------------------------------------------------------
# F3-2  PUT /settings and POST /settings/reset require auth when enabled
# ---------------------------------------------------------------------------

def test_settings_put_requires_auth(client):
    """Once auth is enabled, unauthenticated PUT /settings must return 401."""
    # Register first user so JWT secret is created, then enable auth
    reg = _register(client)
    assert reg.status_code == 200
    token = reg.json()["token"]

    # Enable auth with a valid token
    resp = client.put(
        "/api/v1/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200

    # Now unauthenticated PUT should be blocked
    resp = client.put("/api/v1/settings", json={"theme": "light"})
    assert resp.status_code == 401


def test_settings_reset_requires_auth(client):
    reg = _register(client)
    token = reg.json()["token"]
    client.put(
        "/api/v1/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    # Unauthenticated reset should be blocked
    resp = client.post("/api/v1/settings/reset")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# F3-3  DELETE /logs requires auth when enabled
# ---------------------------------------------------------------------------

def test_logs_delete_requires_auth(client):
    reg = _register(client)
    token = reg.json()["token"]
    client.put(
        "/api/v1/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    resp = client.delete("/api/v1/logs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# F3-5  Auth endpoint tests: register, login, profile, JWT
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_returns_token(self, client):
        resp = _register(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == DEFAULT_TEST_EMAIL

    def test_register_duplicate_email(self, client):
        _register(client)
        resp = _register(client)
        assert resp.status_code == 409

    def test_register_invalid_email(self, client):
        resp = _register(client, email="not-an-email")
        assert resp.status_code == 400

    def test_register_short_password(self, client):
        resp = _register(client, password=INVALID_SHORT_PASSWORD)
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, client):
        _register(client)
        resp = _login(client)
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_login_wrong_password(self, client):
        _register(client)
        resp = _login(client, password=INVALID_WRONG_PASSWORD)
        assert resp.status_code == 401


def test_vault_reset_returns_session_and_revokes_old_session(client):
    reg = _register(client)
    old_token = reg.json()["token"]
    vault_key = reg.json()["vault_key"]

    resp = client.post(
        "/api/v1/auth/vault-reset",
        json={
            "email": DEFAULT_TEST_EMAIL,
            "vault_key": vault_key,
            "new_password": "VaultReset123!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"]
    assert data["user"]["email"] == DEFAULT_TEST_EMAIL

    old_me = client.get("/api/v1/auth/me", headers=_auth_header(old_token))
    assert old_me.status_code == 401

    old_login = _login(client, password=DEFAULT_TEST_PASSWORD)
    assert old_login.status_code == 401

    new_login = _login(client, password="VaultReset123!")
    assert new_login.status_code == 200


def test_vault_reset_rejects_wrong_key(client):
    _register(client)
    resp = client.post(
        "/api/v1/auth/vault-reset",
        json={
            "email": DEFAULT_TEST_EMAIL,
            "vault_key": "invalid-key",
            "new_password": "VaultReset123!",
        },
    )
    assert resp.status_code == 401
    assert "recovery credentials" in resp.json()["detail"]


def test_vault_reset_unlocks_locked_user(client, db):
    from app.db.models import User
    from app.services.settings_service import get_or_create_settings
    from app.services.user_service import record_failed_login

    reg = _register(client)
    vault_key = reg.json()["vault_key"]
    user = db.query(User).filter(User.email == DEFAULT_TEST_EMAIL).first()
    assert user is not None

    cfg = get_or_create_settings(db)
    for _ in range(cfg.login_lockout_attempts):
        record_failed_login(db, user, cfg)
    db.refresh(user)
    assert user.locked_until is not None

    resp = client.post(
        "/api/v1/auth/vault-reset",
        json={
            "email": DEFAULT_TEST_EMAIL,
            "vault_key": vault_key,
            "new_password": "VaultReset123!",
        },
    )
    assert resp.status_code == 200

    db.refresh(user)
    assert user.login_attempts == 0
    assert user.locked_until is None


def test_vault_reset_log_and_response_do_not_leak_secrets(client, db):
    from app.db.models import Log

    reg = _register(client)
    vault_key = reg.json()["vault_key"]
    new_password = "VaultReset123!"

    resp = client.post(
        "/api/v1/auth/vault-reset",
        json={
            "email": DEFAULT_TEST_EMAIL,
            "vault_key": vault_key,
            "new_password": new_password,
        },
    )
    assert resp.status_code == 200
    assert vault_key not in resp.text
    assert new_password not in resp.text

    logs = db.query(Log).filter(Log.action == "password_changed").all()
    combined = " ".join(
        filter(
            None,
            [
                part
                for log in logs
                for part in (log.details, log.diff, log.entity_name, log.actor_name, log.actor)
            ],
        )
    )
    assert vault_key not in combined
    assert new_password not in combined


def test_bootstrap_initialize_can_seed_smtp_settings(client, db):
    from app.db.models import AppSettings
    from app.services.credential_vault import get_vault

    resp = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "bootstrap@example.com",
            "password": BOOTSTRAP_TEST_PASSWORD,
            "theme_preset": "one-dark",
            "api_base_url": "https://cb.example.com",
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "mailer",
            "smtp_password": "Mailer123!",
            "smtp_from_email": "noreply@example.com",
            "smtp_from_name": "Circuit Breaker",
            "smtp_tls": True,
        },
    )
    assert resp.status_code == 200

    cfg = db.get(AppSettings, 1)
    assert cfg is not None
    assert cfg.api_base_url == "https://cb.example.com"
    assert cfg.smtp_enabled is True
    assert cfg.smtp_host == "smtp.example.com"
    assert cfg.smtp_from_email == "noreply@example.com"
    assert cfg.smtp_password_enc is not None
    assert get_vault().decrypt(cfg.smtp_password_enc) == "Mailer123!"


@pytest.mark.asyncio
async def test_forgot_password_callback_tolerates_missing_smtp_library(client, db, monkeypatch):
    from app.core.users import UserManager
    from app.db.models import User
    from app.services import smtp_service
    from app.services.settings_service import get_or_create_settings

    _register(client)
    cfg = get_or_create_settings(db)
    cfg.smtp_enabled = True
    cfg.smtp_host = "smtp.example.com"
    cfg.smtp_port = 587
    cfg.smtp_from_email = "noreply@example.com"
    cfg.smtp_from_name = "Circuit Breaker"
    db.commit()

    monkeypatch.setattr(smtp_service, "aiosmtplib", None)
    user = db.query(User).filter(User.email == DEFAULT_TEST_EMAIL).first()
    assert user is not None

    manager = UserManager(None)
    await manager.on_after_forgot_password(user, "reset-token", None)


@pytest.mark.asyncio
async def test_forgot_password_uses_external_app_url_for_email_links(client, db, monkeypatch):
    from types import SimpleNamespace

    from app.core.users import UserManager
    from app.db.models import User
    from app.services.settings_service import get_or_create_settings
    from app.services.smtp_service import SmtpService

    captured = {}

    async def _capture_send_password_reset(self, to_email, token, base_url):
        captured["to_email"] = to_email
        captured["token"] = token
        captured["base_url"] = base_url

    _register(client)
    cfg = get_or_create_settings(db)
    cfg.smtp_enabled = True
    cfg.smtp_host = "smtp.example.com"
    cfg.smtp_from_email = "noreply@example.com"
    cfg.api_base_url = "https://circuitbreaker.example.com"
    db.commit()

    monkeypatch.setattr(SmtpService, "send_password_reset", _capture_send_password_reset)

    user = db.query(User).filter(User.email == DEFAULT_TEST_EMAIL).first()
    assert user is not None

    manager = UserManager(None)
    request = SimpleNamespace(base_url="http://internal.local/", client=None)
    await manager.on_after_forgot_password(user, "reset-token", request)

    assert captured["to_email"] == DEFAULT_TEST_EMAIL
    assert captured["base_url"] == "https://circuitbreaker.example.com"


class TestProfile:
    def test_get_me_with_token(self, client):
        reg = _register(client)
        token = reg.json()["token"]
        # Need to enable auth for token validation to work
        client.put(
            "/api/v1/settings",
            json={"auth_enabled": True},
            headers=_auth_header(token),
        )
        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["email"] == DEFAULT_TEST_EMAIL

    def test_get_me_no_token(self, client):
        reg = _register(client)
        token = reg.json()["token"]
        client.put(
            "/api/v1/settings",
            json={"auth_enabled": True},
            headers=_auth_header(token),
        )
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_get_me_after_logout_revoked_token_is_unauthorized(self, client):
        reg = _register(client)
        token = reg.json()["token"]
        client.put(
            "/api/v1/settings",
            json={"auth_enabled": True},
            headers=_auth_header(token),
        )

        logout_resp = client.post("/api/v1/auth/logout", headers=_auth_header(token))
        assert logout_resp.status_code == 204

        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# F3-7  DELETE /auth/me — account self-deletion
# ---------------------------------------------------------------------------

def test_delete_me(client):
    reg = _register(client)
    token = reg.json()["token"]
    # Enable auth
    client.put(
        "/api/v1/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    # Delete own account
    resp = client.delete("/api/v1/auth/me", headers=_auth_header(token))
    assert resp.status_code == 204

    # Confirm the user is gone — /me should 401
    resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert resp.status_code == 401


def test_delete_me_unauthenticated(client):
    reg = _register(client)
    token = reg.json()["token"]
    client.put(
        "/api/v1/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    resp = client.delete("/api/v1/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Audit log scrubbing — bootstrap credentials must never appear in logs
# ---------------------------------------------------------------------------

def test_bootstrap_logs_scrub_sensitive_data(client):
    """Audit logs must not expose the bootstrap password or JWT token in plaintext."""
    password = BOOTSTRAP_TEST_PASSWORD
    resp = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "admin@example.com",
            "password": password,
            "theme_preset": "one-dark",
        },
    )
    assert resp.status_code == 200
    token = resp.json()["token"]

    # Bootstrap enables auth — provide the token to access logs
    logs_resp = client.get(
        "/api/v1/logs",
        headers=_auth_header(token),
    )
    assert logs_resp.status_code == 200

    logs_text = logs_resp.text
    assert password not in logs_text, "Plaintext password found in audit logs"
    assert token not in logs_text, "JWT token found in audit logs"
