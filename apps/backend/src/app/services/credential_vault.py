"""Credential vault — Fernet-based symmetric encryption for all secrets.

The vault singleton is intentionally lazy: it holds no key until
``reinitialize(key)`` is called during the application lifespan startup.
This prevents silently generating an ephemeral key at module-import time,
which would make all previously encrypted DB values unreadable after a
restart.

Usage:
    from app.services.credential_vault import get_vault

    vault = get_vault()
    enc = vault.encrypt("my-secret")
    plain = vault.decrypt(enc)
"""

from cryptography.fernet import Fernet


class CredentialVault:
    def __init__(self) -> None:
        self._fernet: Fernet | None = None

    def reinitialize(self, key: str) -> None:
        """Load (or reload) the vault with *key* (base64 URL-safe Fernet key)."""
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise RuntimeError(
                "Vault is not initialized. CB_VAULT_KEY was not found in the "
                "environment, {CB_DATA_DIR}/.env, or the database. Run OOBE to generate a key."
            )
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if self._fernet is None:
            raise RuntimeError(
                "Vault is not initialized. CB_VAULT_KEY was not found in the "
                "environment, {CB_DATA_DIR}/.env, or the database. Run OOBE to generate a key."
            )
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @property
    def is_initialized(self) -> bool:
        return self._fernet is not None


_vault_instance = CredentialVault()


def get_vault() -> CredentialVault:
    return _vault_instance
