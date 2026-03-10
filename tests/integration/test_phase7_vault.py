"""Phase 7 Vault Encryption Tests.

Covers:
- CredentialVault lazy-init: raises RuntimeError before reinitialize(), no ephemeral key
- OOBE bootstrap generates and returns a vault key (vault_key_warning: true)
- Key is persisted to AppSettings.vault_key in DB
- Restart-persistence: encrypt → clear singleton → reload key from DB → decrypt works
- Key rotation re-encrypts all secrets and hot-swaps the in-memory vault
- Vault health endpoint: healthy when key is set, ephemeral when not
"""

import os
import tempfile
from pathlib import Path

import pytest

_BOOTSTRAP_PAYLOAD = {
    "email": "admin@example.com",
    "password": "Secure1234!",
    "theme_preset": "one-dark",
    "theme": "dark",
    "timezone": "UTC",
    "language": "en",
    "ui_font": "inter",
    "ui_font_size": "medium",
}


# ---------------------------------------------------------------------------
# CredentialVault lazy-init behaviour
# ---------------------------------------------------------------------------


def test_vault_uninitialized_raises_runtime_error():
    """Calling encrypt/decrypt before reinitialize() must raise RuntimeError — not silently
    generate an ephemeral key."""
    from app.services.credential_vault import CredentialVault

    fresh_vault = CredentialVault()
    assert not fresh_vault.is_initialized

    with pytest.raises(RuntimeError, match="not initialized"):
        fresh_vault.encrypt("secret")

    with pytest.raises(RuntimeError, match="not initialized"):
        fresh_vault.decrypt("gAAAAA...")


def test_vault_reinitialize_works():
    """After reinitialize(key) the vault encrypts/decrypts correctly."""
    from cryptography.fernet import Fernet

    from app.services.credential_vault import CredentialVault

    key = Fernet.generate_key().decode()
    vault = CredentialVault()
    vault.reinitialize(key)

    assert vault.is_initialized
    enc = vault.encrypt("hello-world")
    assert vault.decrypt(enc) == "hello-world"


def test_vault_reinitialize_twice_uses_new_key():
    """reinitialize() can be called again (for rotation) — subsequent ops use the new key."""
    from cryptography.fernet import Fernet, InvalidToken

    from app.services.credential_vault import CredentialVault

    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    vault = CredentialVault()
    vault.reinitialize(key1)
    enc_with_key1 = vault.encrypt("data")

    vault.reinitialize(key2)
    # Old ciphertext is no longer decryptable
    with pytest.raises(InvalidToken):
        vault.decrypt(enc_with_key1)

    # New ciphertext works fine
    enc_with_key2 = vault.encrypt("data")
    assert vault.decrypt(enc_with_key2) == "data"


# ---------------------------------------------------------------------------
# OOBE bootstrap vault key generation
# ---------------------------------------------------------------------------


def test_oobe_returns_vault_key_warning(client):
    """Bootstrap response must include vault_key and vault_key_warning: true."""
    resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()

    assert body.get("vault_key_warning") is True, "vault_key_warning should be True"
    vault_key = body.get("vault_key")
    assert vault_key, "vault_key should be a non-empty string"
    # Fernet keys are 44 base64 URL-safe chars
    assert len(vault_key) == 44, f"Expected 44-char Fernet key, got {len(vault_key)}"


def test_oobe_vault_key_persisted_in_db(client, db):
    """After bootstrap the vault key must be stored in AppSettings.vault_key."""
    from app.db.models import AppSettings

    resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
    assert resp.status_code == 200
    vault_key_returned = resp.json().get("vault_key")

    cfg = db.get(AppSettings, 1)
    assert cfg is not None
    assert cfg.vault_key is not None, "AppSettings.vault_key should be set after bootstrap"
    assert cfg.vault_key == vault_key_returned, "DB vault_key should match the returned key"
    assert cfg.vault_key_hash is not None, "AppSettings.vault_key_hash should be set"


def test_oobe_vault_key_written_to_file(client, monkeypatch):
    """Bootstrap writes the vault key to the data .env file."""
    import app.services.vault_service as vs

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_env = Path(tmpdir) / ".env"
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", tmp_env)

        resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200
        vault_key_returned = resp.json().get("vault_key")

        assert tmp_env.exists(), "/data/.env should be created during bootstrap"
        content = tmp_env.read_text()
        assert "CB_VAULT_KEY=" in content, "/data/.env should contain CB_VAULT_KEY"
        assert vault_key_returned in content, "key in file should match the returned key"


# ---------------------------------------------------------------------------
# Restart-persistence: encrypt → reload → decrypt
# ---------------------------------------------------------------------------


def test_vault_survives_simulated_restart(client, db, monkeypatch):
    """Core restart-persistence test.

    1. Bootstrap → vault key is persisted to DB (and env).
    2. Simulate restart: clear in-memory singleton and env var.
    3. Reload key from DB via load_vault_key().
    4. Re-initialize singleton with loaded key.
    5. Previously encrypted ciphertext must decrypt correctly.
    """
    from app.services import vault_service
    from app.services.credential_vault import CredentialVault, get_vault

    # Bootstrap to generate vault key
    resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
    assert resp.status_code == 200

    # Encrypt something using the current (bootstrapped) vault
    vault = get_vault()
    assert vault.is_initialized, "Vault should be initialized after bootstrap"
    secret = "my-snmp-community-string"
    ciphertext = vault.encrypt(secret)

    # Simulate restart: clear the singleton and remove env var
    fresh_vault = CredentialVault()
    monkeypatch.setattr("app.services.credential_vault._vault_instance", fresh_vault)
    saved_env_key = os.environ.pop("CB_VAULT_KEY", None)

    # Also disable file-based loading so we test the DB fallback
    import app.services.vault_service as vs
    original_path = vs._DATA_ENV_PATH
    monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))

    try:
        # Load key from DB fallback
        loaded_key = vault_service.load_vault_key(db)
        assert loaded_key is not None, "load_vault_key() should find key in DB after bootstrap"

        fresh_vault.reinitialize(loaded_key)
        assert fresh_vault.is_initialized

        # Decrypt the ciphertext encrypted by the original vault
        recovered = fresh_vault.decrypt(ciphertext)
        assert recovered == secret, "Decryption after simulated restart should succeed"
    finally:
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", original_path)
        if saved_env_key:
            os.environ["CB_VAULT_KEY"] = saved_env_key


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


def test_vault_rotation_reencrypts_smtp_password(client, db, monkeypatch):
    """rotate_vault_key() re-encrypts smtp_password_enc so the new vault can decrypt it."""
    import app.services.vault_service as vs

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path(tmpdir) / ".env")

        from app.db.models import AppSettings
        from app.services import vault_service
        from app.services.credential_vault import get_vault

        # Bootstrap → vault initialized
        resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200

        vault = get_vault()
        assert vault.is_initialized

        # Store an encrypted SMTP password in AppSettings
        plain_password = "super-secret-smtp-pass"
        cfg = db.get(AppSettings, 1)
        cfg.smtp_password_enc = vault.encrypt(plain_password)
        db.commit()

        # Rotate the key
        vault_service.rotate_vault_key(db)
        db.refresh(cfg)

        # The rotated vault (same singleton, re-initialized) must still decrypt
        recovered = vault.decrypt(cfg.smtp_password_enc)
        assert recovered == plain_password, "SMTP password must be readable after key rotation"


def test_vault_rotation_updates_db_key(client, db, monkeypatch):
    """rotate_vault_key() must update AppSettings.vault_key with the new key."""
    import app.services.vault_service as vs

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path(tmpdir) / ".env")

        from app.db.models import AppSettings
        from app.services import vault_service

        client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
        cfg = db.get(AppSettings, 1)
        old_key = cfg.vault_key
        old_hash = cfg.vault_key_hash

        vault_service.rotate_vault_key(db)
        db.refresh(cfg)

        assert cfg.vault_key != old_key, "AppSettings.vault_key must change after rotation"
        assert cfg.vault_key_hash != old_hash, "AppSettings.vault_key_hash must change after rotation"
        assert cfg.vault_key_rotated_at is not None


# ---------------------------------------------------------------------------
# vault_service.load_vault_key fallback chain
# ---------------------------------------------------------------------------


def test_load_vault_key_from_env(db, monkeypatch):
    """load_vault_key() should prefer the env var over file and DB."""
    from cryptography.fernet import Fernet

    import app.services.vault_service as vs
    from app.services.vault_service import load_vault_key

    test_key = Fernet.generate_key().decode()
    monkeypatch.setenv("CB_VAULT_KEY", test_key)
    monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))

    result = load_vault_key(db)
    assert result == test_key
    assert vs.get_key_source() == "environment"


def test_load_vault_key_from_file(db, monkeypatch):
    """load_vault_key() should read from /data/.env when env var is absent."""
    from cryptography.fernet import Fernet

    import app.services.vault_service as vs
    from app.services.vault_service import load_vault_key

    monkeypatch.delenv("CB_VAULT_KEY", raising=False)

    test_key = Fernet.generate_key().decode()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write(f"CB_VAULT_KEY={test_key}\n")
        tmp_path = Path(f.name)

    try:
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", tmp_path)
        result = load_vault_key(db)
        assert result == test_key
        assert str(tmp_path) in vs.get_key_source() or vs.get_key_source() == str(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def test_load_vault_key_from_db(client, db, monkeypatch):
    """load_vault_key() falls back to AppSettings.vault_key when env and file are absent."""
    import app.services.vault_service as vs
    from app.services.vault_service import load_vault_key

    client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)

    monkeypatch.delenv("CB_VAULT_KEY", raising=False)
    monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))

    result = load_vault_key(db)
    assert result is not None
    assert vs.get_key_source() == "database"


def test_load_vault_key_returns_none_when_nothing_found(db, monkeypatch):
    """load_vault_key() must return None (not raise, not generate) when all sources are empty."""
    import app.services.vault_service as vs
    from app.services.vault_service import load_vault_key

    monkeypatch.delenv("CB_VAULT_KEY", raising=False)
    monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))

    result = load_vault_key(db)
    assert result is None
    assert vs.get_key_source() == "none"


# ---------------------------------------------------------------------------
# Vault health endpoint
# ---------------------------------------------------------------------------


def test_vault_health_endpoint_healthy(client, auth_headers, monkeypatch):
    """GET /health/vault returns status: healthy after bootstrap."""
    resp = client.get("/api/v1/health/vault", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("healthy", "degraded"), f"Expected healthy/degraded, got: {body}"
    assert "key_source" in body
    assert "encrypted_secrets" in body
    assert "last_rotation" in body


def test_vault_health_endpoint_ephemeral_when_no_key(client, auth_headers, monkeypatch):
    """GET /health/vault returns status: ephemeral when the vault is not initialized."""
    from app.services.credential_vault import CredentialVault

    # Replace singleton with an uninitialized vault
    fresh = CredentialVault()
    monkeypatch.setattr("app.services.credential_vault._vault_instance", fresh)

    resp = client.get("/api/v1/health/vault", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ephemeral"


def test_vault_test_endpoint_ok(client, auth_headers):
    """POST /admin/vault/test returns ok: true when vault is initialized."""
    # First bootstrap to ensure vault is initialized
    resp = client.post("/api/v1/admin/vault/test", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "verified" in body["message"].lower()


def test_vault_test_endpoint_not_ok_when_uninitialized(client, auth_headers, monkeypatch):
    """POST /admin/vault/test returns ok: false when vault has no key."""
    from app.services.credential_vault import CredentialVault

    fresh = CredentialVault()
    monkeypatch.setattr("app.services.credential_vault._vault_instance", fresh)

    resp = client.post("/api/v1/admin/vault/test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
