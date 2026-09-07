"""The startup phases that run before this process joins the message bus.

Each function is one phase of ``main.lifespan``, in the order the lifespan
calls them, and each is independent of the others except for that order: the
vault must be loaded before anything encrypts, and the schema must exist before
anything reads it.

Failures are deliberately inconsistent, and that is the contract: a broken data
volume, a failed migration or an unloadable vault exit the process, because
serving from that state corrupts data or silently loses it. A missing salt, an
undetectable LAN address or a native-integration hiccup only log, because the
product works without them.
"""

import logging
import os
from pathlib import Path

from app.core.config import settings
from app.core.startup_validation import validate_startup_secrets
from app.db.session import get_session_context
from app.startup.schema import (
    assert_required_schema,
    require_timescale_if_configured,
    run_alembic_upgrade,
    warn_if_rls_without_bypass,
)

_logger = logging.getLogger(__name__)


def validate_data_dir_writable() -> None:
    """Fail fast when the /data volume is not writable.

    Broken volume permissions otherwise surface much later as a cryptic error
    from whichever feature happens to write first.
    """
    # ── Phase 1: Filesystem write validation ───────────────────────────────
    # Fail fast if /data volume permissions are broken (avoids cryptic runtime errors).
    _data_dir = Path(os.environ.get("CB_DATA_DIR", "/data"))
    _test_paths = [
        _data_dir,
        _data_dir / "uploads",
        Path(settings.uploads_dir) if not settings.uploads_dir.startswith("/data") else None,
    ]
    for _path in filter(None, _test_paths):
        try:
            _path.mkdir(parents=True, exist_ok=True)
            _test_file = _path / ".write_test"
            _test_file.touch()
            _test_file.unlink()
        except (PermissionError, OSError) as _pe:
            _logger.critical(
                "STARTUP FAILED: Cannot write to %s. Volume permissions are incorrect. "
                "Fix: docker run --rm -v circuitbreaker-data:/data alpine "
                "sh -c 'chown -R 1000:1000 /data'",
                _path,
            )
            raise SystemExit(1) from _pe
    _logger.info("Filesystem validation passed — data dir: %s", _data_dir)


def apply_pending_migrations() -> None:
    """Bring the schema to head, then assert it is actually there.

    Safe for both single-worker dev and multi-worker prod: if another worker
    already applied the migrations the upgrade is an instant no-op. Set
    CB_AUTO_MIGRATE=false when the entrypoint pre-migrates.
    """
    # ── Phase 1b: Auto-migrate ─────────────────────────────────────────────
    # Run pending Alembic migrations before any schema check.  Safe for both
    # single-worker dev (make dev) and multi-worker prod: if another worker
    # already applied the migrations the upgrade call is an instant no-op.
    # Set CB_AUTO_MIGRATE=false to disable (e.g. when entrypoint pre-migrates).
    auto_migrate_enabled = os.environ.get("CB_AUTO_MIGRATE", "true").lower() != "false"
    if auto_migrate_enabled:
        try:
            run_alembic_upgrade()
            _logger.info("Alembic migrations applied (or already at head).")
        except Exception as _me:
            _logger.critical(
                "Auto-migrate failed: %s — fix the database or run "
                "'make migrate' / 'alembic upgrade head', then restart.",
                _me,
                exc_info=True,
            )
            raise SystemExit(1) from _me

    if auto_migrate_enabled:
        assert_required_schema()
    else:
        _logger.info("Schema validation skipped because migrations were pre-applied.")
    require_timescale_if_configured()
    warn_if_rls_without_bypass()


def warn_on_default_client_salt() -> None:
    """Warn when the shipped public salt is still in use for client pre-hashes."""
    # ── Phase 1b: Warn if default client hash salt is in use ──────────────
    from app.core.security import _DEFAULT_SALT, get_client_salt

    try:
        with get_session_context() as _salt_db:
            if get_client_salt(_salt_db) == _DEFAULT_SALT:
                _logger.warning(
                    "SECURITY: CB_CLIENT_SALT is not set and no custom salt is stored in "
                    "AppSettings. The default public salt 'circuitbreaker-salt-v1' is in use. "
                    "Set CB_CLIENT_SALT to a unique random value to prevent rainbow table "
                    "attacks on client-side password pre-hashes."
                )
    except Exception:
        pass  # Non-fatal — vault may not be ready yet on first boot


def autodetect_api_base_url() -> None:
    """Give native installs an api_base_url so invite links point at the UI.

    Left null, invite emails embed the backend URL (localhost:8000) rather than
    the frontend one.
    """

    # ── Phase 1c: Auto-detect api_base_url ────────────────────────────────
    # On native installs api_base_url is often null, causing invite emails to
    # embed the backend URL (localhost:8000) instead of the frontend URL.
    # If unset, detect the LAN IP and default to http://<ip>:8088 (native port).
    def _detect_lan_ip() -> str | None:
        import socket as _socket

        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
                _s.connect(("8.8.8.8", 80))
                return str(_s.getsockname()[0])
        except Exception:
            return None

    try:
        with get_session_context() as _url_db:
            from app.services.settings_service import get_or_create_settings as _get_settings

            _url_cfg = _get_settings(_url_db)
            if not _url_cfg.api_base_url:
                _lan_ip = _detect_lan_ip()
                if _lan_ip and not _lan_ip.startswith("127."):
                    _url_cfg.api_base_url = f"http://{_lan_ip}:8088"
                    _url_db.commit()
                    _logger.info("Auto-set api_base_url to %s", _url_cfg.api_base_url)
    except Exception as _url_exc:
        _logger.debug("api_base_url auto-detect skipped: %s", _url_exc)


def init_vault() -> None:
    """Load the Fernet vault key and validate the startup secrets.

    Must run before any scheduler job or service that encrypts or decrypts.
    Fallback chain: env CB_VAULT_KEY, then /data/.env, then AppSettings.
    """
    # ── Phase 7: Vault key init ────────────────────────────────────────────
    # Must run before any scheduler job or service that encrypts/decrypts.
    # Fallback chain: env CB_VAULT_KEY → /data/.env → AppSettings.vault_key
    try:
        with get_session_context() as _vault_db:
            from app.services import vault_service as _vault_svc
            from app.services.credential_vault import get_vault as _get_vault

            _vault_key = _vault_svc.load_vault_key(_vault_db)
            from app.services.settings_service import (
                get_or_create_settings as _settings_for_secrets,
            )

            _startup_cfg = _settings_for_secrets(_vault_db)
            _secret_errors = validate_startup_secrets(
                jwt_secret=_startup_cfg.jwt_secret,
                vault_key=_vault_key,
            )
            if _secret_errors:
                raise RuntimeError("; ".join(_secret_errors))
            if _vault_key:
                _get_vault().reinitialize(_vault_key)
                import os as _os

                _os.environ["CB_VAULT_KEY"] = _vault_key
                _logger.info("Vault initialized from: %s", _vault_svc.get_key_source())
            elif _vault_svc._count_encrypted_secrets(_vault_db) > 0:
                raise RuntimeError(
                    "Vault encryption key is missing but encrypted secrets exist; set CB_VAULT_KEY "
                    "or restore the persisted vault key before startup"
                )
            else:
                _logger.warning(
                    "CB_VAULT_KEY not found in environment, %s, or database. "
                    "Vault is uninitialized — encrypted credentials will be unavailable "
                    "until OOBE completes and a vault key is generated.",
                    _vault_svc._DATA_ENV_PATH,
                )
    except Exception as _ve:
        _logger.critical("Vault init failed during startup: %s", _ve, exc_info=True)
        raise SystemExit(1) from _ve


def bootstrap_native_integration() -> None:
    """Ensure the built-in monitors integration row exists."""
    # ── Native integration bootstrap ───────────────────────────────────────
    with get_session_context() as _native_db:
        try:
            from app.db.models import Integration as _Integration

            _native = _native_db.query(_Integration).filter(_Integration.type == "native").first()
            if not _native:
                _native = _Integration(
                    type="native",
                    name="Built-in Monitors",
                    enabled=True,
                    sync_interval_s=60,
                )
                _native_db.add(_native)
                _native_db.commit()
                _logger.info("Native integration bootstrapped (id=%d)", _native.id)
            else:
                _logger.debug("Native integration already exists (id=%d)", _native.id)
        except Exception as _ne:
            _logger.warning("Native integration bootstrap failed: %s", _ne)
