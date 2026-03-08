"""Vault service — key loading, generation, persistence, and rotation.

Key loading fallback chain (load_vault_key):
  1. Process environment variable CB_VAULT_KEY
  2. /data/.env file (CB_VAULT_KEY=...)
  3. AppSettings.vault_key in the database
  4. Returns None — caller decides whether to warn or fail

This order ensures that after any container restart, as long as
/data/.env or the DB row is intact, the same Fernet key is loaded
and all previously encrypted ciphertext remains valid.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import stat
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.services.credential_vault import get_vault

_logger = logging.getLogger(__name__)

_DATA_ENV_PATH = Path(os.environ.get("CB_DATA_DIR", "/data")) / ".env"
_ENV_KEY_RE = re.compile(r"^CB_VAULT_KEY\s*=\s*(.+)$", re.MULTILINE)

_key_source: str = "none"


def _is_valid_fernet_key(key: str) -> bool:
    """Return True if *key* is a valid base64 URL-safe 32-byte Fernet key."""
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
        return True
    except Exception:
        return False


def get_key_source() -> str:
    """Return a human-readable string describing where the active key was loaded from."""
    return _key_source


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_vault_key_valid(db: Session, candidate: str) -> bool:
    """Return True when *candidate* matches the configured vault key."""
    candidate_norm = (candidate or "").strip()
    if not candidate_norm:
        return False

    try:
        from app.db.models import AppSettings

        cfg = db.get(AppSettings, 1)
        if cfg and cfg.vault_key_hash:
            if hmac.compare_digest(_sha256(candidate_norm), cfg.vault_key_hash):
                return True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Could not verify vault key against database hash: %s", exc)

    active_key = load_vault_key(db)
    return bool(active_key) and hmac.compare_digest(candidate_norm, active_key)  # type: ignore[type-var]


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def load_vault_key(db: Session) -> str | None:
    """Try each key source in order; return the first non-empty key found."""
    global _key_source

    # 1. Process environment variable
    env_key = os.environ.get("CB_VAULT_KEY", "").strip()
    if env_key and _is_valid_fernet_key(env_key):
        _key_source = "environment"
        return env_key
    elif env_key:
        _logger.warning(
            "CB_VAULT_KEY environment variable is set but is not a valid Fernet key "
            "(likely a placeholder). Falling through to file / database sources."
        )

    # 2. /data/.env file
    if _DATA_ENV_PATH.exists():
        try:
            content = _DATA_ENV_PATH.read_text(encoding="utf-8")
            m = _ENV_KEY_RE.search(content)
            if m:
                file_key = m.group(1).strip()
                if file_key:
                    _key_source = str(_DATA_ENV_PATH)
                    return file_key
        except OSError as exc:
            _logger.warning("Could not read vault key from %s: %s", _DATA_ENV_PATH, exc)

    # 3. AppSettings.vault_key in the database
    try:
        from app.db.models import AppSettings

        cfg = db.get(AppSettings, 1)
        if cfg and cfg.vault_key and cfg.vault_key.strip():
            _key_source = "database"
            return cfg.vault_key.strip()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Could not read vault key from database: %s", exc)

    _key_source = "none"
    return None


# ---------------------------------------------------------------------------
# Key generation & persistence
# ---------------------------------------------------------------------------


def generate_vault_key() -> str:
    """Generate a fresh Fernet key and return it as a base64 URL-safe string."""
    return Fernet.generate_key().decode()


def write_vault_key_to_env(key: str) -> None:
    """Write (or update) CB_VAULT_KEY in /data/.env, with 0600 permissions."""
    try:
        _DATA_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

        if _DATA_ENV_PATH.exists():
            content = _DATA_ENV_PATH.read_text(encoding="utf-8")
            if _ENV_KEY_RE.search(content):
                content = _ENV_KEY_RE.sub(f"CB_VAULT_KEY={key}", content)
            else:
                content = content.rstrip("\n") + f"\nCB_VAULT_KEY={key}\n"
        else:
            content = f"CB_VAULT_KEY={key}\n"

        _DATA_ENV_PATH.write_text(content, encoding="utf-8")
        _DATA_ENV_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        _logger.info("Vault key written to %s", _DATA_ENV_PATH)
    except OSError as exc:
        _logger.warning(
            "Could not write vault key to %s: %s — storing in DB only.", _DATA_ENV_PATH, exc
        )


def _persist_key_to_db(db: Session, key: str) -> None:
    """Store the vault key and its hash in AppSettings (DB fallback)."""
    from app.db.models import AppSettings

    cfg = db.get(AppSettings, 1)
    if cfg:
        cfg.vault_key = key
        cfg.vault_key_hash = _sha256(key)
        cfg.vault_key_rotated_at = utcnow()
        db.commit()


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


def rotate_vault_key(db: Session) -> None:
    """Generate a new vault key, re-encrypt all secrets, and persist the new key.

    Covers:
      - AppSettings.smtp_password_enc
      - DiscoveryProfile.snmp_community_encrypted
      - credentials table (encrypted_value)

    After rotation the in-memory vault singleton is reinitialized with the new
    key so subsequent encrypt/decrypt calls use it immediately.
    """
    from app.db.models import AppSettings, Credential, DiscoveryProfile
    from app.services.log_service import write_log

    vault = get_vault()
    if not vault.is_initialized:
        raise RuntimeError("Cannot rotate vault key — vault is not currently initialized.")

    new_key_str = generate_vault_key()
    new_fernet = Fernet(new_key_str.encode())

    def _reencrypt(ciphertext: str) -> str:
        plain = vault.decrypt(ciphertext)
        return new_fernet.encrypt(plain.encode()).decode()

    # Re-encrypt AppSettings.smtp_password_enc
    cfg = db.get(AppSettings, 1)
    if cfg and cfg.smtp_password_enc:
        try:
            cfg.smtp_password_enc = _reencrypt(cfg.smtp_password_enc)
        except Exception as exc:
            _logger.warning("Could not re-encrypt SMTP password during rotation: %s", exc)

    # Re-encrypt DiscoveryProfile.snmp_community_encrypted
    profiles = (
        db.query(DiscoveryProfile)
        .filter(DiscoveryProfile.snmp_community_encrypted.isnot(None))
        .all()
    )
    for profile in profiles:
        try:
            profile.snmp_community_encrypted = _reencrypt(profile.snmp_community_encrypted)  # type: ignore[arg-type]
        except Exception as exc:
            _logger.warning(
                "Could not re-encrypt SNMP community for profile %d: %s", profile.id, exc
            )

    # Re-encrypt credentials table
    credentials = db.query(Credential).all()
    for cred in credentials:
        try:
            cred.encrypted_value = _reencrypt(cred.encrypted_value)
        except Exception as exc:
            _logger.warning("Could not re-encrypt credential %d during rotation: %s", cred.id, exc)

    db.flush()

    # Persist new key to file and DB
    write_vault_key_to_env(new_key_str)
    if cfg:
        cfg.vault_key = new_key_str
        cfg.vault_key_hash = _sha256(new_key_str)
        cfg.vault_key_rotated_at = utcnow()

    db.commit()

    # Hot-swap the in-memory vault so future operations use the new key
    vault.reinitialize(new_key_str)

    # Also inject into the process environment for consistency
    os.environ["CB_VAULT_KEY"] = new_key_str

    global _key_source
    _key_source = str(_DATA_ENV_PATH)

    _logger.info("Vault key rotated successfully.")

    try:
        write_log(
            db,
            action="vault_key_rotated",
            entity_type="app_settings",
            entity_id=1,
            details=f"new_key_hash_prefix={_sha256(new_key_str)[:16]}",
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Status reporting
# ---------------------------------------------------------------------------


def _count_encrypted_secrets(db: Session) -> int:
    from app.db.models import AppSettings, Credential, DiscoveryProfile

    count = 0
    try:
        cfg = db.get(AppSettings, 1)
        if cfg and cfg.smtp_password_enc:
            count += 1
    except Exception:  # noqa: BLE001
        pass
    try:
        count += (
            db.query(DiscoveryProfile)
            .filter(DiscoveryProfile.snmp_community_encrypted.isnot(None))
            .count()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        count += db.query(Credential).count()
    except Exception:  # noqa: BLE001
        pass
    return count


def _resolve_vault_status(db: Session) -> str:
    from app.db.models import AppSettings

    vault = get_vault()
    if not vault.is_initialized:
        return "ephemeral"
    current_key = os.environ.get("CB_VAULT_KEY", "")
    try:
        cfg = db.get(AppSettings, 1)
        if cfg and cfg.vault_key_hash and current_key:
            return "healthy" if _sha256(current_key) == cfg.vault_key_hash else "degraded"
    except Exception:  # noqa: BLE001
        pass
    return "healthy"


def get_vault_status(db: Session) -> dict:
    """Return a status dict for GET /api/v1/health/vault."""
    from app.db.models import AppSettings

    last_rotated: str | None = None
    try:
        cfg = db.get(AppSettings, 1)
        if cfg and cfg.vault_key_rotated_at:
            last_rotated = cfg.vault_key_rotated_at.isoformat()
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": _resolve_vault_status(db),
        "key_source": _key_source,
        "encrypted_secrets": _count_encrypted_secrets(db),
        "last_rotation": last_rotated,
    }
