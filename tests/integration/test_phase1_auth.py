"""Phase 1 tests: FastAPI-Users auth, rate-limit profiles, legacy token, bootstrap."""

from .conftest import _read_setup_token

# SEC-4 (6be8c8d9) made `setup_token` a required field on the bootstrap body, so
# every POST below has to present the one-time token the server wrote under
# CB_DATA_DIR; without it Pydantic answers 422 before the handler runs.


class TestBootstrapFlow:
    """OOBE bootstrap creates a superuser and returns a valid token."""

    def test_bootstrap_status_fresh(self, client):
        resp = client.get("/api/v1/bootstrap/status")
        assert resp.status_code == 200
        assert resp.json()["needs_bootstrap"] is True

    def test_bootstrap_initialize(self, client):
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": _read_setup_token(client),
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "admin@lab.local"
        assert data["user"]["is_admin"] is True
        assert data["user"]["is_superuser"] is True

    def test_bootstrap_rejects_double_init(self, client):
        setup_token = _read_setup_token(client)
        first = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": setup_token,
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        assert first.status_code == 200
        # Replay the consumed token: /bootstrap/status stops publishing the token
        # path once auth is on, so this is the only way to send a well-formed second
        # request — and the 409 must come from "already bootstrapped", not from a
        # missing field.
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": setup_token,
                "email": "admin2@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
            # The first call left a session cookie behind, so this one is CSRF-checked.
            headers={"X-CSRF-Token": client.cookies.get("cb_csrf") or ""},
        )
        assert resp.status_code == 409


class TestLegacyLogin:
    """Legacy auth endpoints still work for backward compat."""

    def test_legacy_login_and_me(self, client):
        client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": _read_setup_token(client),
                "email": "user@lab.local",
                "password": "Secure1234!",
                "theme_preset": "one-dark",
            },
        )
        login_resp = client.post(
            "/api/v1/auth/login",
            json={
                "email": "user@lab.local",
                "password": "Secure1234!",
            },
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]

        me_resp = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
            },
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == "user@lab.local"


class TestLegacyAPIToken:
    """CB_API_TOKEN god-mode is deprecated — refused unless CB_LEGACY_AUTH rolls it back.

    This class used to assert the bare env var still granted admin. It does not:
    LegacyTokenMiddleware now answers 401 with a migration notice when a Bearer
    matches CB_API_TOKEN, and only honours it while CB_LEGACY_AUTH=true, the
    documented rollback toggle. Both halves are pinned below so neither the
    refusal nor the escape hatch can regress unnoticed.
    """

    def _bootstrap(self, client):
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": _read_setup_token(client),
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        assert resp.status_code == 200, resp.text

    def test_api_token_rejected_without_rollback_flag(self, client, monkeypatch):
        monkeypatch.setenv("CB_API_TOKEN", "test-static-token")
        monkeypatch.delenv("CB_LEGACY_AUTH", raising=False)
        self._bootstrap(client)

        resp = client.get(
            "/api/v1/hardware",
            headers={
                "Authorization": "Bearer test-static-token",
            },
        )
        assert resp.status_code == 401
        assert "CB_API_TOKEN is deprecated" in resp.json()["detail"]

    def test_api_token_bypass(self, client, monkeypatch):
        monkeypatch.setenv("CB_API_TOKEN", "test-static-token")
        monkeypatch.setenv("CB_LEGACY_AUTH", "true")
        self._bootstrap(client)

        resp = client.get(
            "/api/v1/hardware",
            headers={
                "Authorization": "Bearer test-static-token",
            },
        )
        assert resp.status_code == 200


class TestPasswordValidation:
    """Password complexity rules are enforced."""

    def test_weak_password_rejected(self, client):
        client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": _read_setup_token(client),
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "weak@lab.local",
                "password": "short",
            },
        )
        assert resp.status_code == 400


class TestAppSettingsFields:
    """Newly activated AppSettings fields are readable/writable."""

    def test_settings_include_new_fields(self, client):
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "registration_open" in data
        assert "rate_limit_profile" in data
        assert data["registration_open"] is True
        assert data["rate_limit_profile"] == "normal"

    def test_update_rate_limit_profile(self, client, auth_headers):
        # Authenticated: cd1724ff (P0-4) stopped the unbootstrapped app from handing
        # the admin sentinel to writes, so an anonymous PUT /settings is 401. The
        # field being writable is what this test is about, so it writes as an admin.
        resp = client.put(
            "/api/v1/settings", json={"rate_limit_profile": "strict"}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["rate_limit_profile"] == "strict"


class TestRateLimitProfiles:
    """Rate-limit profile resolution returns correct strings."""

    def test_profile_values(self):
        from app.core.rate_limit import PROFILES

        assert "relaxed" in PROFILES
        assert "normal" in PROFILES
        assert "strict" in PROFILES
        assert PROFILES["strict"]["auth"] == "3/minute"
        assert PROFILES["relaxed"]["auth"] == "20/minute"
