"""Tests for the CredentialVault Fernet-based encryption service."""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.credential_vault import CredentialVault

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vault(key: str | None = None) -> CredentialVault:
    """Return a fresh, initialized CredentialVault with *key* (or a new key)."""
    k = key or Fernet.generate_key().decode()
    v = CredentialVault()
    v.reinitialize(k)
    return v


# ---------------------------------------------------------------------------
# Unit tests — no I/O, no app startup required
# ---------------------------------------------------------------------------


class TestEncryptProducesCiphertext:
    def test_ciphertext_differs_from_plaintext(self):
        vault = _make_vault()
        plaintext = "super-secret-password"
        ciphertext = vault.encrypt(plaintext)
        assert ciphertext != plaintext

    def test_ciphertext_is_a_string(self):
        vault = _make_vault()
        ciphertext = vault.encrypt("hello")
        assert isinstance(ciphertext, str)
        assert len(ciphertext) > 0


class TestRoundTrip:
    def test_encrypt_decrypt_returns_original(self):
        vault = _make_vault()
        original = "my-community-string-42"
        assert vault.decrypt(vault.encrypt(original)) == original

    def test_round_trip_empty_string(self):
        vault = _make_vault()
        assert vault.decrypt(vault.encrypt("")) == ""

    def test_round_trip_unicode(self):
        vault = _make_vault()
        original = "p@$$w0rd-中文-émoji🔐"
        assert vault.decrypt(vault.encrypt(original)) == original


class TestCrossKeyDecryption:
    def test_different_keys_cannot_cross_decrypt(self):
        """Ciphertext produced by vault_a must not be decryptable by vault_b."""
        vault_a = _make_vault()
        vault_b = _make_vault()

        ciphertext = vault_a.encrypt("secret-value")

        with pytest.raises((InvalidToken, Exception)):
            vault_b.decrypt(ciphertext)


class TestTamperedCiphertext:
    def test_tampered_ciphertext_raises(self):
        vault = _make_vault()
        ciphertext = vault.encrypt("tamper-me")

        # Flip a character near the middle of the token
        chars = list(ciphertext)
        mid = len(chars) // 2
        chars[mid] = "A" if chars[mid] != "A" else "B"
        tampered = "".join(chars)

        with pytest.raises((InvalidToken, Exception)):
            vault.decrypt(tampered)

    def test_completely_wrong_bytes_raises(self):
        vault = _make_vault()
        with pytest.raises(InvalidToken):
            vault.decrypt("not-a-valid-fernet-token")


class TestEnvironmentKeysSeparation:
    def test_jwt_secret_and_vault_key_differ(self):
        """The test environment must use distinct secrets for JWT and vault."""
        jwt_secret = os.environ.get("CB_JWT_SECRET", "")
        vault_key = os.environ.get("CB_VAULT_KEY", "")

        assert jwt_secret, "CB_JWT_SECRET env var is not set"
        assert vault_key, "CB_VAULT_KEY env var is not set"
        assert jwt_secret != vault_key, "CB_JWT_SECRET and CB_VAULT_KEY must be different values"


class TestUninitializedVault:
    def test_uninitialized_vault_encrypt_raises(self):
        vault = CredentialVault()
        with pytest.raises(RuntimeError, match="not initialized"):
            vault.encrypt("anything")

    def test_uninitialized_vault_decrypt_raises(self):
        vault = CredentialVault()
        with pytest.raises(RuntimeError, match="not initialized"):
            vault.decrypt("anything")

    def test_is_initialized_false_before_reinitialize(self):
        vault = CredentialVault()
        assert vault.is_initialized is False

    def test_is_initialized_true_after_reinitialize(self):
        vault = _make_vault()
        assert vault.is_initialized is True
