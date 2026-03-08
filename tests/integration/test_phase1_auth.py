"""Phase 1 tests: FastAPI-Users auth, rate-limit profiles, legacy token, bootstrap."""


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
        client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": "admin2@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
        assert resp.status_code == 409


class TestLegacyLogin:
    """Legacy auth endpoints still work for backward compat."""

    def test_legacy_login_and_me(self, client):
        client.post(
            "/api/v1/bootstrap/initialize",
            json={
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
    """CB_API_TOKEN env var still grants admin access."""

    def test_api_token_bypass(self, client, monkeypatch):
        monkeypatch.setenv("CB_API_TOKEN", "test-static-token")
        # Enable auth via bootstrap first
        client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": "admin@lab.local",
                "password": "Admin1234!",
                "theme_preset": "one-dark",
            },
        )
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

    def test_update_rate_limit_profile(self, client):
        resp = client.put("/api/v1/settings", json={"rate_limit_profile": "strict"})
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
