"""Vault service — key loading, generation, persistence, and rotation.

Key loading fallback chain (load_vault_key):
  1. Process environment variable CB_VAULT_KEY
    2. CB_DATA_DIR/.env file (CB_VAULT_KEY=...)
  3. AppSettings.vault_key in the database
  4. Returns None — caller decides whether to warn or fail

This order ensures that after any container restart, as long as
CB_DATA_DIR/.env or the DB row is intact, the same Fernet key is loaded
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


def _get_data_dir() -> Path:
    return Path(os.environ.get("CB_DATA_DIR") or (Path.cwd() / "data")).expanduser()


_DATA_ENV_PATH = _get_data_dir() / ".env"
_ENV_KEY_RE = re.compile(r"^CB_VAULT_KEY\s*=\s*(.+)$", re.MULTILINE)

_key_source: str = "none"
_active_key: str | None = None


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
        _logger.warning(
            "Could not verify vault key against database hash (reason: %s)",
            type(exc).__name__,
        )

    active_key = load_vault_key(db)
    return bool(active_key) and hmac.compare_digest(candidate_norm, active_key)  # type: ignore[type-var]


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def load_vault_key(db: Session) -> str | None:
    """Try each key source in order; return the first non-empty key found.

    Before accepting the environment variable key, this function cross-checks
    it against the stored vault_key_hash in the database.  A syntactically
    valid-but-stale Fernet key (e.g. the original CB_VAULT_KEY env var after
    an auto-rotation) would otherwise win over the rotated key in data/.env,
    causing every restart to report "degraded".
    """
    global _key_source, _active_key

    # 1. Process environment variable
    env_key = os.environ.get("CB_VAULT_KEY", "").strip()
    if env_key and _is_valid_fernet_key(env_key):
        # Cross-check against the stored hash before accepting.
        # If a hash is present and doesn't match, the env var is stale (pre-rotation).
        try:
            from app.db.models import AppSettings

            cfg = db.get(AppSettings, 1)
            if cfg and cfg.vault_key_hash:
                if hmac.compare_digest(_sha256(env_key), cfg.vault_key_hash):
                    _key_source = "environment"
                    _active_key = env_key
                    return env_key
                else:
                    _logger.warning(
                        "CB_VAULT_KEY env var is a valid Fernet key but does not match "
                        "the stored vault_key_hash — it is stale (likely from before an "
                        "auto-rotation). Falling through to file / database sources."
                    )
                    # Fall through — do NOT return the stale key
            else:
                # No hash stored yet (first-time setup): env var is authoritative.
                _key_source = "environment"
                _active_key = env_key
                return env_key
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Could not verify CB_VAULT_KEY against database hash (reason: %s) — "
                "falling through to file / database sources.",
                type(exc).__name__,
            )
            # Fall through — do NOT short-circuit; data/.env or DB key may be correct.
    elif env_key:
        _logger.warning(
            "CB_VAULT_KEY environment variable is set but is not a valid Fernet key "
            "(likely a placeholder). Falling through to file / database sources."
        )

    # 2. CB_DATA_DIR/.env file
    if _DATA_ENV_PATH.exists():
        try:
            content = _DATA_ENV_PATH.read_text(encoding="utf-8")
            m = _ENV_KEY_RE.search(content)
            if m:
                file_key = m.group(1).strip()
                if file_key and _is_valid_fernet_key(file_key):
                    _key_source = str(_DATA_ENV_PATH)
                    _active_key = file_key
                    return file_key
        except OSError as exc:
            _logger.warning(
                "Could not read vault key from %s (reason: %s)",
                _DATA_ENV_PATH,
                type(exc).__name__,
            )

    # 3. AppSettings.vault_key in DB (fallback when env/file absent or unwritable)
    try:
        from app.db.models import AppSettings

        cfg = db.get(AppSettings, 1)
        if cfg and getattr(cfg, "vault_key", None):
            db_key = (cfg.vault_key or "").strip()
            if db_key and _is_valid_fernet_key(db_key):
                _key_source = "database"
                _active_key = db_key
                return db_key
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "Could not read vault key from database (reason: %s)",
            type(exc).__name__,
        )

    _key_source = "none"
    _active_key = None
    return None


# ---------------------------------------------------------------------------
# Key generation & persistence
# ---------------------------------------------------------------------------


def generate_vault_key() -> str:
    """Generate a fresh Fernet key and return it as a base64 URL-safe string."""
    return Fernet.generate_key().decode()


def write_vault_key_to_env(key: str) -> None:
    """Write (or update) CB_VAULT_KEY in CB_DATA_DIR/.env, with 0600 permissions."""
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
            "Could not write vault key to %s (reason: %s) — storing in DB only.",
            _DATA_ENV_PATH,
            type(exc).__name__,
        )


def _persist_key_to_db(db: Session, key: str) -> None:
    """Store the vault key hash in AppSettings."""
    from app.db.models import AppSettings

    cfg = db.get(AppSettings, 1)
    if cfg:
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

    # Integrity probe: verify the active key can decrypt before mutating anything.
    # If the vault was loaded with a stale key (e.g. original CB_VAULT_KEY env var
    # after an auto-rotation), every _reencrypt call would silently fail, producing
    # orphaned ciphertext encrypted with new_key but unreadable by it.
    _probe: str | None = None
    _probe_label = "unknown"
    try:
        _cfg_p = db.get(AppSettings, 1)
        if _cfg_p and _cfg_p.smtp_password_enc:
            _probe, _probe_label = _cfg_p.smtp_password_enc, "AppSettings.smtp_password_enc"
    except Exception:  # noqa: BLE001
        pass
    if _probe is None:
        try:
            _pp = (
                db.query(DiscoveryProfile)
                .filter(DiscoveryProfile.snmp_community_encrypted.isnot(None))
                .first()
            )
            if _pp:
                _probe = _pp.snmp_community_encrypted
                _probe_label = f"DiscoveryProfile(id={_pp.id})"
        except Exception:  # noqa: BLE001
            pass
    if _probe is None:
        try:
            _pc = db.query(Credential).first()
            if _pc and _pc.encrypted_value:
                _probe, _probe_label = _pc.encrypted_value, f"Credential(id={_pc.id})"
        except Exception:  # noqa: BLE001
            pass
    if _probe is not None:
        try:
            vault.decrypt(_probe)
        except Exception as exc:
            _logger.error(
                "rotate_vault_key ABORTED: current vault key cannot decrypt '%s' (%s). "
                "The vault was loaded with a stale key — restore the correct key first. "
                "No data has been modified.",
                _probe_label,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"Vault key integrity check failed: cannot decrypt {_probe_label}. "
                "Rotation aborted to prevent data loss."
            ) from exc

    new_key_str = generate_vault_key()
    new_fernet = Fernet(new_key_str.encode())

    def _reencrypt(ciphertext: str) -> str:
        plain = vault.decrypt(ciphertext)
        return new_fernet.encrypt(plain.encode()).decode()

    # Re-encrypt AppSettings.smtp_password_enc
    cfg = db.get(AppSettings, 1)  # AppSettings already imported above
    if cfg and cfg.smtp_password_enc:
        try:
            cfg.smtp_password_enc = _reencrypt(cfg.smtp_password_enc)
        except Exception as exc:
            _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                # Logs only type(exc).__name__ — exception class name, not any credential value
                "Could not re-encrypt SMTP password during rotation (reason: %s)",
                type(exc).__name__,
            )

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
                "Could not re-encrypt SNMP community for profile %d (reason: %s)",
                profile.id,
                type(exc).__name__,
            )

    # Re-encrypt credentials table
    credentials = db.query(Credential).all()
    for cred in credentials:
        try:
            cred.encrypted_value = _reencrypt(cred.encrypted_value)
        except Exception as exc:
            _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                # Logs only type(exc).__name__ — exception class name, not any credential value
                "Could not re-encrypt credential %d during rotation (reason: %s)",
                cred.id,
                type(exc).__name__,
            )

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

    global _key_source, _active_key
    _key_source = str(_DATA_ENV_PATH)
    _active_key = new_key_str

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


def initialize_vault_key(db: Session) -> None:
    """Generate and persist the first vault key when none exists yet.

    Safety guard: refuse initialization if encrypted secrets already exist while
    the vault is uninitialized, because generating a fresh key would make those
    ciphertexts permanently unreadable.
    """
    from app.services.log_service import write_log
    from app.services.settings_service import get_or_create_settings

    vault = get_vault()
    if vault.is_initialized:
        raise RuntimeError("Vault is already initialized.")

    if _count_encrypted_secrets(db) > 0:
        raise RuntimeError(
            "Cannot initialize a new vault key while encrypted secrets already exist. "
            "Restore the original key or recover from backup first."
        )

    cfg = get_or_create_settings(db)
    new_key_str = generate_vault_key()

    write_vault_key_to_env(new_key_str)
    cfg.vault_key = new_key_str
    cfg.vault_key_hash = _sha256(new_key_str)
    cfg.vault_key_rotated_at = utcnow()
    db.commit()

    vault.reinitialize(new_key_str)
    os.environ["CB_VAULT_KEY"] = new_key_str

    global _key_source, _active_key
    _key_source = str(_DATA_ENV_PATH)
    _active_key = new_key_str

    _logger.info("Vault key initialized successfully.")

    try:
        write_log(
            db,
            action="vault_key_initialized",
            entity_type="app_settings",
            entity_id=getattr(cfg, "id", 1),
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
    # Prefer the module-level _active_key (set by load_vault_key, initialize_vault_key,
    # and rotate_vault_key) over the environment variable.  The env var can be stale in
    # multi-worker setups or before load_vault_key's hash cross-check runs.
    current_key = _active_key or os.environ.get("CB_VAULT_KEY", "")
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
