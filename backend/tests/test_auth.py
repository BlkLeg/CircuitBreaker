"""
Auth system tests — covers gaps F3-1 through F3-7.

Uses the existing ``client`` / ``db`` fixtures from conftest.py (in-memory SQLite).
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enable_auth(client):
    """Enable auth via settings and return the settings payload."""
    resp = client.put("/api/v1/settings", json={"auth_enabled": True})
    return resp.json()


def _register(client, email="test@example.com", password="Secure1234!", display_name=None):
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


def _login(client, email="test@example.com", password="Secure1234!"):
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
            "password": "Secure1234!",
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
            "password": "Secure1234!",
            "theme_preset": "one-dark",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/bootstrap/initialize",
        json={
            "email": "second@example.com",
            "password": "Secure1234!",
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
        assert data["user"]["email"] == "test@example.com"

    def test_register_duplicate_email(self, client):
        _register(client)
        resp = _register(client)
        assert resp.status_code == 409

    def test_register_invalid_email(self, client):
        resp = _register(client, email="not-an-email")
        assert resp.status_code == 400

    def test_register_short_password(self, client):
        resp = _register(client, password="short")
        assert resp.status_code == 400


class TestLogin:
    def test_login_success(self, client):
        _register(client)
        resp = _login(client)
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_login_wrong_password(self, client):
        _register(client)
        resp = _login(client, password="wrongpassword")
        assert resp.status_code == 401


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
        assert resp.json()["email"] == "test@example.com"

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
    password = "Secure1234!"
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
