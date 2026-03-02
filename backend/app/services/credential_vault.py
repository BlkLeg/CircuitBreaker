import os
from cryptography.fernet import Fernet


def _get_or_create_key() -> bytes:
    """
    Reads encryption key from env var CB_VAULT_KEY.
    If not set, generates a key, logs a warning, and uses an ephemeral key
    (data is lost on restart — acceptable for dev only).
    """
    key = os.environ.get("CB_VAULT_KEY")
    if not key:
        import logging
        logging.getLogger(__name__).warning(
            "CB_VAULT_KEY not set. Generating ephemeral key. "
            "Telemetry credentials will not persist across restarts."
        )
        key = Fernet.generate_key().decode()
    return key.encode()


class CredentialVault:
    def __init__(self):
        self.fernet = Fernet(_get_or_create_key())

    def encrypt(self, plaintext: str) -> str:
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self.fernet.decrypt(ciphertext.encode()).decode()


_vault_instance = CredentialVault()


def get_vault() -> CredentialVault:
    return _vault_instance
