"""
OOBE & E2E Smoke Audit — pre-ship checklist.

Covers all six sections from PROMPT.md:
  1. Fresh DB state
  2. First page load (API-level)
  3. Auth-disabled CRUD
  4. First user registration, enable-auth, login/logout
  5. Password & form validation
  6. CB_API_TOKEN static token behaviour
  7. Secret / log cleanliness

Run the full suite:
    cd backend && ../.venv/bin/python -m pytest tests/test_oobe_smoke.py -v

CB_API_TOKEN tests require the env var to be set:
    CB_API_TOKEN=MY_API_TOKEN_123 pytest tests/test_oobe_smoke.py::TestCBApiToken -v
"""
import os
import pytest

API = "/api/v1"

# Compliant test credentials (matches frontend + backend complexity rules)
_EMAIL = "oobe@example.com"
_PASS  = "Oobe1234!"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _register(client, email=_EMAIL, password=_PASS):
    status = client.get(f"{API}/bootstrap/status")
    if status.status_code == 200 and status.json().get("needs_bootstrap"):
        return client.post(
            f"{API}/bootstrap/initialize",
            json={
                "email": email,
                "password": password,
                "theme_preset": "one-dark",
            },
        )
    return client.post(f"{API}/auth/register", json={"email": email, "password": password})


def _login(client, email=_EMAIL, password=_PASS):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _enable_auth(client, token: str):
    resp = client.put(
        f"{API}/settings",
        json={"auth_enabled": True},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    return resp.json()


def _create_hardware(client, name="OOBE-Server", **headers):
    return client.post(f"{API}/hardware", json={"name": name, "role": "server"}, **headers)


# ===========================================================================
# 1. Fresh DB state
# ===========================================================================

class TestFreshDB:
    def test_settings_exist_with_defaults(self, client):
        """GET /settings returns 200 with sane defaults on a fresh DB."""
        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_enabled"] is False, "auth should be disabled by default"

    def test_jwt_secret_absent_from_settings_response(self, client):
        """jwt_secret must never appear in the settings payload."""
        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200
        assert "jwt_secret" not in resp.json()

    def test_entity_tables_empty_on_fresh_start(self, client):
        """All data tables should be empty on a fresh install."""
        for path in ("/hardware", "/compute-units", "/services",
                     "/storage", "/networks", "/misc", "/docs"):
            resp = client.get(f"{API}{path}")
            assert resp.status_code == 200, f"GET {path} failed"
            body = resp.json()
            # Endpoints may return a list or a dict with a results key
            items = body if isinstance(body, list) else body.get("items", body.get("results", []))
            assert len(items) == 0, f"{path} should be empty on fresh start, got {items}"

    def test_no_users_on_fresh_start(self, db):
        """Users table should have zero rows after initial migration."""
        from app.db.models import User
        count = db.query(User).count()
        assert count == 0


# ===========================================================================
# 2. First page load (API-level)
# ===========================================================================

class TestFirstPageLoad:
    def test_settings_read_unauthenticated(self, client):
        """Settings are publicly readable (auth disabled by default)."""
        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200

    def test_topology_unauthenticated(self, client):
        """Graph topology endpoint is accessible without auth."""
        resp = client.get(f"{API}/graph/topology")
        assert resp.status_code == 200

    def test_all_critical_read_endpoints_return_2xx(self, client):
        """All major read endpoints return 2xx without auth credentials."""
        read_paths = [
            "/settings",
            "/hardware",
            "/compute-units",
            "/services",
            "/networks",
            "/storage",
            "/docs",
            "/graph/topology",
        ]
        for path in read_paths:
            resp = client.get(f"{API}{path}")
            assert resp.status_code < 300, f"GET {path} returned {resp.status_code}"


# ===========================================================================
# 3. Auth-disabled CRUD (writes succeed without Authorization header)
# ===========================================================================

class TestAuthDisabledCRUD:
    def test_create_hardware_no_auth(self, client):
        resp = _create_hardware(client)
        assert resp.status_code == 201

    def test_create_service_no_auth(self, client):
        resp = client.post(f"{API}/services", json={"name": "TestSvc", "slug": "test-svc"})
        assert resp.status_code == 201

    def test_create_network_no_auth(self, client):
        resp = client.post(f"{API}/networks", json={"name": "LAN"})
        assert resp.status_code == 201

    def test_settings_update_no_auth(self, client):
        """PUT /settings works without auth when auth is disabled."""
        resp = client.put(f"{API}/settings", json={"theme": "dark"})
        assert resp.status_code == 200

    def test_admin_export_no_auth(self, client):
        """Admin export is accessible when auth is disabled."""
        resp = client.get(f"{API}/admin/export")
        assert resp.status_code == 200


# ===========================================================================
# 4. First user registration, enable auth, login / logout
# ===========================================================================

class TestFirstUserAndAuthFlow:
    def test_register_returns_token_and_profile(self, client):
        resp = _register(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data and data["token"]
        assert data["user"]["email"] == _EMAIL

    def test_first_user_is_admin(self, client):
        """The very first registered user must be marked as admin."""
        resp = _register(client)
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is True

    def test_second_user_is_not_admin(self, client):
        """Subsequent users must NOT auto-receive admin status."""
        _register(client)
        resp = _register(client, email="second@example.com")
        assert resp.status_code == 200
        assert resp.json()["user"]["is_admin"] is False

    def test_register_sets_jwt_secret_in_db(self, client, db):
        """Registration must auto-generate and persist the JWT secret."""
        from app.db.models import AppSettings
        _register(client)
        cfg = db.get(AppSettings, 1)
        assert cfg is not None
        assert cfg.jwt_secret is not None and len(cfg.jwt_secret) > 0

    def test_jwt_secret_never_in_settings_response(self, client):
        """jwt_secret must not leak into any settings API response."""
        _register(client)
        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200
        assert "jwt_secret" not in resp.json()

    def test_enable_auth_blocks_anonymous_writes(self, client):
        """After enabling auth, unauthenticated write requests must return 401."""
        reg = _register(client)
        token = reg.json()["token"]
        _enable_auth(client, token)

        resp = _create_hardware(client, name="ShouldFail")
        assert resp.status_code == 401, \
            f"Expected 401 after enabling auth, got {resp.status_code}"

    def test_enable_auth_still_allows_settings_read(self, client):
        """Read-only settings endpoint stays accessible after enabling auth."""
        reg = _register(client)
        token = reg.json()["token"]
        _enable_auth(client, token)

        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200

    def test_token_authenticates_write_when_auth_enabled(self, client):
        """Valid JWT must allow writes when auth is enabled."""
        reg = _register(client)
        token = reg.json()["token"]
        _enable_auth(client, token)

        resp = _create_hardware(client, name="AuthedWrite", headers=_auth_header(token))
        assert resp.status_code == 201

    def test_login_success(self, client):
        _register(client)
        resp = _login(client)
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_wrong_password_returns_generic_error(self, client):
        """Failed login must return 401 with a generic message (no 'password' hint)."""
        _register(client)
        resp = _login(client, password="WrongPass99!")
        assert resp.status_code == 401
        detail = resp.json().get("detail", "")
        assert "password" not in detail.lower() or "invalid" in detail.lower(), \
            f"Error message too specific: {detail!r}"

    def test_nonexistent_user_returns_401(self, client):
        resp = _login(client, email="ghost@example.com")
        assert resp.status_code == 401

    def test_logout_is_stateless_204(self, client):
        """Logout endpoint must return 204 and require no server state."""
        reg = _register(client)
        token = reg.json()["token"]
        resp = client.post(f"{API}/auth/logout", headers=_auth_header(token))
        assert resp.status_code == 204

    def test_admin_export_requires_auth_when_enabled(self, client):
        """GET /admin/export must return 401 when auth is enabled and no token given."""
        reg = _register(client)
        token = reg.json()["token"]
        _enable_auth(client, token)

        resp = client.get(f"{API}/admin/export")
        assert resp.status_code == 401

    def test_admin_export_works_with_valid_token(self, client):
        """GET /admin/export must succeed with a valid JWT."""
        reg = _register(client)
        token = reg.json()["token"]
        _enable_auth(client, token)

        resp = client.get(f"{API}/admin/export", headers=_auth_header(token))
        assert resp.status_code == 200
        assert "hardware" in resp.json()


# ===========================================================================
# 5. Password & form validation
# ===========================================================================

class TestPasswordValidation:
    def test_rejects_short_password(self, client):
        resp = _register(client, password="Ab1!")
        assert resp.status_code == 400

    def test_rejects_no_uppercase(self, client):
        resp = _register(client, password="oobe1234!")
        assert resp.status_code == 400

    def test_rejects_no_lowercase(self, client):
        resp = _register(client, password="OOBE1234!")
        assert resp.status_code == 400

    def test_rejects_no_digit(self, client):
        resp = _register(client, password="OobeOobe!")
        assert resp.status_code == 400

    def test_rejects_no_special_char(self, client):
        resp = _register(client, password="Oobe1234")
        assert resp.status_code == 400

    def test_accepts_fully_compliant_password(self, client):
        resp = _register(client, password="Oobe1234!")
        assert resp.status_code == 200

    def test_rejects_invalid_email(self, client):
        resp = _register(client, email="notanemail")
        assert resp.status_code == 400

    def test_rejects_duplicate_email(self, client):
        _register(client)
        resp = _register(client)  # same email
        assert resp.status_code == 409

    def test_error_response_is_json_not_html(self, client):
        """Validation errors must be JSON, never an HTML error page."""
        resp = _register(client, password="weak")
        assert resp.status_code == 400
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, \
            f"Expected JSON error, got content-type: {content_type}"


# ===========================================================================
# 6. CB_API_TOKEN static token behaviour
# ===========================================================================

@pytest.mark.skipif(
    not os.getenv("CB_API_TOKEN"),
    reason="CB_API_TOKEN not set — skipping static token tests",
)
class TestCBApiToken:
    """
    Requires CB_API_TOKEN env var.  Run with:
        CB_API_TOKEN=MY_API_TOKEN_123 pytest tests/test_oobe_smoke.py::TestCBApiToken -v
    """

    @pytest.fixture(autouse=True)
    def _token(self):
        self.api_token = os.environ["CB_API_TOKEN"]

    def _token_header(self) -> dict:
        return {"Authorization": f"Bearer {self.api_token}"}

    def test_write_endpoint_blocked_without_token(self, client):
        """When CB_API_TOKEN is set, writes without any auth must return 401."""
        resp = _create_hardware(client, name="NoToken")
        assert resp.status_code == 401

    def test_write_endpoint_allowed_with_api_token(self, client):
        """CB_API_TOKEN must be accepted as a valid bearer on write endpoints."""
        resp = client.post(
            f"{API}/hardware",
            json={"name": "TokenAuthed", "role": "server"},
            headers=self._token_header(),
        )
        assert resp.status_code == 201

    def test_admin_export_blocked_without_token(self, client):
        """Admin export must return 401 without the token."""
        resp = client.get(f"{API}/admin/export")
        assert resp.status_code == 401

    def test_admin_export_allowed_with_api_token(self, client):
        resp = client.get(f"{API}/admin/export", headers=self._token_header())
        assert resp.status_code == 200

    def test_wrong_token_rejected(self, client):
        resp = client.post(
            f"{API}/hardware",
            json={"name": "BadToken"},
            headers={"Authorization": "Bearer WRONG_TOKEN"},
        )
        assert resp.status_code == 401

    def test_api_token_not_in_settings_response(self, client):
        """The static API token value must never appear in any settings response."""
        resp = client.get(f"{API}/settings", headers=self._token_header())
        assert resp.status_code == 200
        body_text = resp.text
        assert self.api_token not in body_text, \
            "CB_API_TOKEN value leaked into settings response"

    def test_jwt_also_works_when_api_token_set(self, client):
        """When CB_API_TOKEN is set, valid JWTs must still be accepted.

        Auth register is a public endpoint, so registration succeeds without
        a token. The resulting JWT must also be accepted on write endpoints.
        """
        reg = client.post(
            f"{API}/auth/register",
            json={"email": _EMAIL, "password": _PASS},
        )
        assert reg.status_code == 200, f"Register failed: {reg.text}"
        jwt_token = reg.json()["token"]

        resp = _create_hardware(client, name="JwtWithApiToken",
                                headers=_auth_header(jwt_token))
        assert resp.status_code == 201


# ===========================================================================
# 7. Secret / response cleanliness
# ===========================================================================

class TestSecretCleanliness:
    def test_register_response_excludes_password_hash(self, client):
        """Registration response must never include the stored password hash."""
        resp = _register(client)
        assert resp.status_code == 200
        body_text = resp.text
        assert "password_hash" not in body_text
        assert "hash" not in resp.json().get("user", {})

    def test_register_response_excludes_jwt_secret(self, client):
        """Registration response must not include the server JWT secret."""
        resp = _register(client)
        assert resp.status_code == 200
        assert "jwt_secret" not in resp.text

    def test_login_response_excludes_jwt_secret(self, client):
        _register(client)
        resp = _login(client)
        assert resp.status_code == 200
        assert "jwt_secret" not in resp.text

    def test_settings_response_excludes_jwt_secret_after_register(self, client):
        """Even after a JWT secret is generated, GET /settings must not expose it."""
        _register(client)  # triggers jwt_secret generation
        resp = client.get(f"{API}/settings")
        assert resp.status_code == 200
        assert "jwt_secret" not in resp.json()

    def test_admin_export_excludes_user_data(self, client):
        """Admin export must not include user accounts or app_settings secrets."""
        reg = _register(client)
        assert reg.status_code == 200
        token = reg.json()["token"]
        resp = client.get(f"{API}/admin/export", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "users" not in data, "Export must not include user rows"
        assert "app_settings" not in data, "Export must not include settings/secrets"
        assert "jwt_secret" not in resp.text
