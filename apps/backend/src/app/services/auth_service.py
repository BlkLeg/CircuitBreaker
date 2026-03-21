"""Auth business logic: register, login, profile management."""

import hashlib
import json
import logging
import os
import re
import secrets as _secrets
from pathlib import Path
from typing import Any

import bcrypt as _bcrypt
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings as _settings
from app.core.rbac import ROLE_DEFAULT_SCOPES
from app.core.security import create_token, gravatar_hash, hash_password, verify_password
from app.core.time import utcnow, utcnow_iso
from app.db.models import AppSettings, Log, Onboarding, User
from app.schemas.auth import (
    AuthResponse,
    BootstrapInitializeOAuthRequest,
    BootstrapInitializeResponse,
    BootstrapStatusResponse,
    BootstrapThemeResponse,
    OnboardingStepResponse,
    UserProfile,
)

_logger = logging.getLogger(__name__)

_MSG_BOOTSTRAP_DONE = "Bootstrap already completed. Please refresh and log in."
_MSG_OAUTH_TOKEN_INVALID = "OAuth token is invalid or expired"

# Pre-computed bcrypt hash used when the looked-up user does not exist, ensuring that
# verify_password() always runs and login response time is constant regardless of whether
# the email address is registered (prevents timing-based email enumeration).
_DUMMY_HASH: str = _bcrypt.hashpw(b"cb-dummy-not-real", _bcrypt.gensalt(rounds=12)).decode()

_PROFILES_DIR = Path(_settings.uploads_dir) / "profiles"
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_PILLOW_FORMAT_TO_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_PILLOW_FORMAT_TO_EXT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "GIF": "gif",
    "WEBP": "webp",
}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hard limits applied before any regex to prevent polynomial backtracking on
# arbitrarily large user-supplied strings (ReDoS mitigation).
_MAX_EMAIL_LEN = 254  # RFC 5321 maximum
_MAX_PASSWORD_LEN = 1024


def _scopes_for_role(role: str) -> str:
    resolved = (role or "viewer").lower()
    if resolved not in ROLE_DEFAULT_SCOPES:
        resolved = "viewer"
    return json.dumps(sorted(ROLE_DEFAULT_SCOPES[resolved]))


def _to_profile(user: User) -> UserProfile:
    if user.profile_photo and user.profile_photo.startswith(("http://", "https://")):
        photo_url = user.profile_photo
    elif user.profile_photo:
        photo_url = f"/uploads/profiles/{user.profile_photo}"
    else:
        photo_url = None
    role = getattr(user, "role", None) or ("admin" if user.is_admin else "viewer")
    try:
        scopes = json.loads(getattr(user, "scopes", "[]") or "[]")
        if not isinstance(scopes, list):
            scopes = []
    except Exception:
        scopes = []
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gravatar_hash=user.gravatar_hash,
        is_admin=user.is_admin,
        is_superuser=user.is_superuser,
        language=user.language or "en",
        profile_photo_url=photo_url,
        mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
        role=role,
        scopes=[str(s) for s in scopes if str(s).strip()],
    )


def _make_token(user: User, cfg: AppSettings) -> str:
    if not cfg.jwt_secret:
        raise RuntimeError("JWT secret not configured")
    try:
        scopes = json.loads(getattr(user, "scopes", "[]") or "[]")
        if not isinstance(scopes, list):
            scopes = []
    except Exception:
        scopes = []
    de = getattr(user, "demo_expires", None)
    demo_expires = de.isoformat() if de is not None else None
    return create_token(
        user.id,
        cfg.jwt_secret,
        cfg.session_timeout_hours,
        role=getattr(user, "role", None),
        scopes=[str(s) for s in scopes if str(s).strip()],
        demo_expires=demo_expires,
    )


def _is_client_hash(value: str) -> bool:
    """True if value looks like a client-side SHA256 hex (64 hex chars)."""
    if len(value) != 64:
        return False
    return all(c in "0123456789abcdef" for c in value.lower())


def _validate_password(password: str) -> None:
    """Enforce complexity rules matching the frontend RULES array."""
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("one special character")
    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"Password must contain: {', '.join(errors)}",
        )


def _normalise_smtp_bootstrap_payload(
    *,
    smtp_enabled: bool | None,
    smtp_host: str | None,
    smtp_port: int | None,
    smtp_username: str | None,
    smtp_password: str | None,
    smtp_from_email: str | None,
    smtp_from_name: str | None,
    smtp_tls: bool | None,
) -> dict[str, Any] | None:
    host = (smtp_host or "").strip()
    from_email = (smtp_from_email or "").strip().lower()
    if not smtp_enabled and not host:
        return None
    if not host or not from_email:
        raise HTTPException(status_code=400, detail="SMTP host and from email are required")
    if len(from_email) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(from_email):
        raise HTTPException(status_code=400, detail="Invalid SMTP from email address")

    port = smtp_port or 587
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="SMTP port must be between 1 and 65535")

    return {
        "smtp_enabled": True,
        "smtp_host": host,
        "smtp_port": port,
        "smtp_username": (smtp_username or "").strip(),
        "smtp_password": smtp_password or None,
        "smtp_from_email": from_email,
        "smtp_from_name": (smtp_from_name or "Circuit Breaker").strip() or "Circuit Breaker",
        "smtp_tls": True if smtp_tls is None else bool(smtp_tls),
    }


def reset_local_user_password(
    db: Session,
    user: User,
    new_password_or_hash: str,
    *,
    source: str,
    update_last_login: bool = False,
) -> User:
    from app.services.log_service import write_log
    from app.services.user_service import revoke_all_sessions

    if not getattr(user, "hashed_password", None):
        raise HTTPException(
            status_code=400, detail="Password reset is unavailable for this account"
        )

    if len(new_password_or_hash) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    if _is_client_hash(new_password_or_hash):
        # Client sent SHA256(password+salt) hex; store bcrypt of that hash.
        pass
    else:
        _validate_password(new_password_or_hash)

    revoke_all_sessions(db, user.id)

    user.hashed_password = hash_password(new_password_or_hash)
    user.force_password_change = False
    user.login_attempts = 0
    user.locked_until = None
    if update_last_login:
        user.last_login = utcnow_iso()
    db.commit()
    db.refresh(user)

    write_log(
        db=None,
        action="password_changed",
        entity_type="user",
        entity_id=user.id,
        entity_name=user.email,
        severity="info",
        category="auth",
        actor_name=user.display_name or user.email,
        actor_id=user.id,
        details=json.dumps({"source": source}),
    )
    return user


def vault_reset_password(
    db: Session,
    email: str,
    vault_key: str,
    new_password_or_hash: str,
    cfg: AppSettings,
    *,
    request: Any = None,
    auto_login: bool = True,
) -> AuthResponse | User:
    from app.services.log_service import write_log
    from app.services.user_service import record_session
    from app.services.vault_service import is_vault_key_valid

    email_norm = email.strip().lower()
    generic_error = HTTPException(
        status_code=401,
        detail="Unable to reset password with the provided recovery credentials",
    )

    if len(email_norm) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(email_norm):
        raise generic_error
    if not is_vault_key_valid(db, vault_key):
        write_log(
            db=None,
            action="vault_reset_failed",
            entity_type="auth",
            entity_name=email_norm,
            severity="warn",
            category="auth",
            actor_name="anonymous",
            ip_address=request.client.host if request and request.client else None,
            details="Vault-key recovery attempt rejected",
        )
        raise generic_error

    user = db.query(User).filter(User.email == email_norm).first()
    if not user or not user.is_active or not getattr(user, "hashed_password", None):
        write_log(
            db=None,
            action="vault_reset_failed",
            entity_type="auth",
            entity_name=email_norm,
            severity="warn",
            category="auth",
            actor_name="anonymous",
            ip_address=request.client.host if request and request.client else None,
            details="Vault-key recovery attempt rejected",
        )
        raise generic_error

    reset_local_user_password(
        db, user, new_password_or_hash, source="vault_key", update_last_login=auto_login
    )

    if not auto_login:
        return user

    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


def register(
    db: Session,
    email: str,
    password_or_hash: str,
    cfg: AppSettings,
    display_name: str | None = None,
) -> AuthResponse:
    if db.query(User).count() == 0:
        raise HTTPException(
            status_code=409,
            detail="Bootstrap required. Use /api/v1/bootstrap/initialize for first account setup.",
        )

    if len(email) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(password_or_hash) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    if _is_client_hash(password_or_hash):
        pass
    else:
        _validate_password(password_or_hash)

    is_first_user = db.query(User).count() == 0

    now = utcnow_iso()
    user = User(
        email=email.strip().lower(),
        hashed_password=hash_password(password_or_hash),
        gravatar_hash=gravatar_hash(email),
        display_name=display_name.strip()
        if display_name and display_name.strip()
        else email.split("@")[0],
        language=cfg.language or "en",
        is_admin=is_first_user,
        is_superuser=is_first_user,
        is_active=True,
        created_at=now,
        role="admin" if is_first_user else "viewer",
        scopes=_scopes_for_role("admin" if is_first_user else "viewer"),
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from None

    # Auto-generate jwt_secret if not yet set (user is registering before enabling auth in settings)
    if not cfg.jwt_secret:
        cfg.jwt_secret = _secrets.token_hex(32)
        db.commit()

    from app.services.log_service import write_log

    write_log(
        db=None,
        action="register_user",
        entity_type="user",
        entity_id=user.id,
        entity_name=user.display_name or user.email,
        severity="info",
        category="auth",
        actor_name=user.display_name or user.email,
        actor_id=user.id,
    )

    token = _make_token(user, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


def bootstrap_status(db: Session) -> BootstrapStatusResponse:
    from app.core.security import get_client_salt

    try:
        user_count = db.query(User).count()
        cfg = db.query(AppSettings).first()
        # Bootstrap is complete only after auth is explicitly enabled in OOBE.
        # jwt_secret may be generated earlier (e.g. OAuth callback), so it is
        # not a reliable completion marker.
        needs_bootstrap = cfg is None or not bool(cfg.auth_enabled)
        return BootstrapStatusResponse(
            needs_bootstrap=needs_bootstrap,
            user_count=user_count,
            client_hash_salt=get_client_salt(db),
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            "bootstrap_status check failed (DB likely empty): %s", e
        )
        return BootstrapStatusResponse(needs_bootstrap=True, user_count=0)


def _derive_display_name(email: str, display_name: str | None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    local = email.strip().lower().split("@")[0]
    cleaned = re.sub(r"[._\-]+", " ", local).strip()
    if not cleaned:
        return "Admin"
    return " ".join(part.capitalize() for part in cleaned.split())


def _generate_and_persist_vault_key(db: Session) -> str | None:
    """Generate the first vault key during OOBE and return the plaintext copy.

    Returns ``None`` when a vault key already exists or generation fails.
    """
    try:
        from app.services import vault_service
        from app.services.credential_vault import get_vault

        cfg_fresh = db.get(AppSettings, 1)
        if cfg_fresh and (cfg_fresh.vault_key or cfg_fresh.vault_key_hash):
            return None

        new_key = vault_service.generate_vault_key()
        vault_service.write_vault_key_to_env(new_key)

        import hashlib
        import os

        if cfg_fresh:
            cfg_fresh.vault_key = new_key
            cfg_fresh.vault_key_hash = hashlib.sha256(new_key.encode()).hexdigest()
            cfg_fresh.vault_key_rotated_at = utcnow()
            db.commit()

        os.environ["CB_VAULT_KEY"] = new_key
        get_vault().reinitialize(new_key)
        _logger.info("Vault key generated and stored during OOBE bootstrap.")
        return new_key
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Vault key generation during OOBE failed: %s", exc)
        return None


def bootstrap_initialize(
    db: Session,
    cfg: AppSettings,
    email: str,
    password_or_hash: str,
    theme_preset: str,
    display_name: str | None = None,
    api_base_url: str | None = None,
    timezone: str | None = None,
    language: str | None = None,
    ui_font: str | None = None,
    ui_font_size: str | None = None,
    theme: str | None = None,
    weather_location: str | None = None,
    smtp_enabled: bool | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_username: str | None = None,
    smtp_password: str | None = None,
    smtp_from_email: str | None = None,
    smtp_from_name: str | None = None,
    smtp_tls: bool | None = None,
) -> BootstrapInitializeResponse:
    email_norm = email.strip().lower()
    public_base_url = (api_base_url or "").strip() or None
    if len(email_norm) > _MAX_EMAIL_LEN or not _EMAIL_RE.match(email_norm):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(password_or_hash) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    if _is_client_hash(password_or_hash):
        pass
    else:
        _validate_password(password_or_hash)
    smtp_bootstrap = _normalise_smtp_bootstrap_payload(
        smtp_enabled=smtp_enabled,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from_email=smtp_from_email,
        smtp_from_name=smtp_from_name,
        smtp_tls=smtp_tls,
    )

    # Bootstrap completion is tracked via auth_enabled, not jwt_secret.
    if bool(cfg.auth_enabled):
        db.rollback()
        raise HTTPException(status_code=409, detail=_MSG_BOOTSTRAP_DONE)

    # Clean up any stale users that exist from a pre-OOBE development database
    # (users created before the bootstrap flow was introduced, without auth configured).
    stale_count = db.query(User).count()
    if stale_count > 0:
        db.query(User).delete()
        db.flush()

    now = utcnow_iso()
    user = User(
        email=email_norm,
        hashed_password=hash_password(password_or_hash),
        gravatar_hash=gravatar_hash(email_norm),
        display_name=_derive_display_name(email_norm, display_name),
        language=language or "en",
        is_admin=True,
        is_superuser=True,
        is_active=True,
        created_at=now,
        role="admin",
        scopes=_scopes_for_role("admin"),
    )
    db.add(user)
    db.flush()  # assign user.id so audit logs can reference it

    _actor_display = user.display_name or user.email

    cfg.auth_enabled = True
    cfg.theme_preset = theme_preset
    if theme in {"dark", "light", "auto"}:
        cfg.theme = theme
    if weather_location and weather_location.strip():
        cfg.weather_location = weather_location.strip()
    if ui_font:
        cfg.ui_font = ui_font
    if ui_font_size:
        cfg.ui_font_size = ui_font_size
    if not cfg.jwt_secret:
        cfg.jwt_secret = _secrets.token_hex(32)
    if not cfg.client_hash_salt:
        # Use CB_CLIENT_SALT env if set, else generate a random hex
        cfg.client_hash_salt = os.getenv("CB_CLIENT_SALT", _secrets.token_hex(32))
    if language in {"en", "es", "fr", "de", "zh", "ja"}:
        cfg.language = language
    if timezone:
        from zoneinfo import available_timezones

        if timezone == "UTC" or timezone in available_timezones():
            cfg.timezone = timezone
            _ts_tz = utcnow()
            tz_log = Log(
                timestamp=_ts_tz,
                created_at_utc=_ts_tz.isoformat(),
                level="info",
                category="settings",
                action="update_timezone",
                actor=_actor_display,
                actor_name=_actor_display,
                actor_id=user.id,
                actor_gravatar_hash=user.gravatar_hash,
                details=f'Timezone set to "{timezone}" during initial setup',
                status_code=200,
            )
            db.add(tz_log)

    _ts = utcnow()
    audit_log = Log(
        timestamp=_ts,
        created_at_utc=_ts.isoformat(),
        level="info",
        category="bootstrap",
        action="bootstrap_create_user",
        actor=_actor_display,
        actor_name=_actor_display,
        actor_id=user.id,
        actor_gravatar_hash=gravatar_hash(email_norm),
        entity_type="user",
        entity_id=user.id,
        details=json.dumps(
            {
                "email": email_norm,
                "theme_preset": theme_preset,
                "language": cfg.language,
                "ui_font": cfg.ui_font,
                "ui_font_size": cfg.ui_font_size,
            }
        ),
        status_code=200,
    )
    db.add(audit_log)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from None

    token = _make_token(user, cfg)

    # Record last_login and session for the bootstrapped admin.
    user.last_login = utcnow_iso()
    db.commit()
    db.refresh(user)
    from app.services.user_service import record_session

    record_session(db, user, None, token, cfg)

    # ── Phase 7: Generate and persist the vault key ────────────────────────
    vault_key_plaintext = _generate_and_persist_vault_key(db)

    settings_bootstrap: dict[str, object] = {}
    if public_base_url:
        settings_bootstrap["api_base_url"] = public_base_url
    if smtp_bootstrap:
        settings_bootstrap.update(smtp_bootstrap)

    if settings_bootstrap:
        try:
            from app.schemas.settings import AppSettingsUpdate
            from app.services.settings_service import update_settings

            update_settings(db, AppSettingsUpdate(**settings_bootstrap), user_id=user.id)  # type: ignore[arg-type]
        except Exception as settings_exc:  # noqa: BLE001
            _logger.warning("Bootstrap settings setup during OOBE failed: %s", settings_exc)

    _set_onboarding_step(db, "finish")

    return BootstrapInitializeResponse(
        token=token,
        user=_to_profile(user),
        theme=BootstrapThemeResponse(preset=cfg.theme_preset or theme_preset),
        vault_key=vault_key_plaintext,
        vault_key_warning=vault_key_plaintext is not None,
    )


def bootstrap_initialize_oauth(
    db: Session,
    cfg: AppSettings,
    payload: BootstrapInitializeOAuthRequest,
) -> BootstrapInitializeResponse:
    """Complete bootstrap when the first admin signed up via OAuth instead of local credentials."""
    from app.core.security import decode_token, gravatar_hash

    # Guard: only valid while auth hasn't been fully enabled yet.
    # The user-count check is intentionally omitted — retrying OAuth with the same
    # account creates the same user (upsert), and retrying with a different account
    # may leave orphaned rows; what matters is that setup isn't finished yet.
    if cfg.auth_enabled:
        raise HTTPException(status_code=409, detail=_MSG_BOOTSTRAP_DONE)

    if not cfg.jwt_secret:
        raise HTTPException(status_code=400, detail=_MSG_OAUTH_TOKEN_INVALID)

    user_id = decode_token(payload.oauth_token, cfg.jwt_secret)
    if user_id is None:
        raise HTTPException(status_code=400, detail=_MSG_OAUTH_TOKEN_INVALID)

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=400, detail=_MSG_OAUTH_TOKEN_INVALID)

    smtp_bootstrap = _normalise_smtp_bootstrap_payload(
        smtp_enabled=payload.smtp_enabled,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password=payload.smtp_password,
        smtp_from_email=payload.smtp_from_email,
        smtp_from_name=payload.smtp_from_name,
        smtp_tls=payload.smtp_tls,
    )

    # Promote the OAuth user to admin
    if payload.display_name and payload.display_name.strip():
        user.display_name = payload.display_name.strip()
    user.role = "admin"
    user.scopes = _scopes_for_role("admin")
    user.is_admin = True
    user.is_superuser = True
    user.gravatar_hash = gravatar_hash(user.email)
    user.language = payload.language or "en"

    _actor_display = user.display_name or user.email

    # Apply OOBE settings
    cfg.auth_enabled = True
    cfg.theme_preset = payload.theme_preset
    if payload.theme in {"dark", "light", "auto"}:
        cfg.theme = payload.theme
    if payload.weather_location and payload.weather_location.strip():
        cfg.weather_location = payload.weather_location.strip()
    if payload.ui_font:
        cfg.ui_font = payload.ui_font
    if payload.ui_font_size:
        cfg.ui_font_size = payload.ui_font_size
    if payload.language in {"en", "es", "fr", "de", "zh", "ja"}:
        cfg.language = payload.language
    if payload.timezone:
        from zoneinfo import available_timezones

        if payload.timezone == "UTC" or payload.timezone in available_timezones():
            cfg.timezone = payload.timezone
            _ts_tz = utcnow()
            tz_log = Log(
                timestamp=_ts_tz,
                created_at_utc=_ts_tz.isoformat(),
                level="info",
                category="settings",
                action="update_timezone",
                actor=_actor_display,
                actor_name=_actor_display,
                actor_id=user.id,
                actor_gravatar_hash=user.gravatar_hash,
                details=f'Timezone set to "{payload.timezone}" during initial setup',
                status_code=200,
            )
            db.add(tz_log)

    _ts = utcnow()
    audit_log = Log(
        timestamp=_ts,
        created_at_utc=_ts.isoformat(),
        level="info",
        category="bootstrap",
        action="bootstrap_create_user",
        actor=_actor_display,
        actor_name=_actor_display,
        actor_id=user.id,
        actor_gravatar_hash=user.gravatar_hash,
        entity_type="user",
        entity_id=user.id,
        details=json.dumps(
            {
                "email": user.email,
                "provider": getattr(user, "provider", "oauth"),
                "theme_preset": payload.theme_preset,
                "language": cfg.language,
                "ui_font": cfg.ui_font,
                "ui_font_size": cfg.ui_font_size,
            }
        ),
        status_code=200,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(user)

    # jwt_secret was already set during the OAuth redirect; re-issue a fresh token
    token = _make_token(user, cfg)

    user.last_login = utcnow_iso()
    db.commit()
    db.refresh(user)
    from app.services.user_service import record_session

    record_session(db, user, None, token, cfg)

    # Generate/persist the first vault key for OAuth bootstrap too, and return the
    # plaintext copy so the OOBE ceremony can show it to the user.
    vault_key_plaintext = _generate_and_persist_vault_key(db)

    # Apply api_base_url / SMTP via settings_service (same as local bootstrap path)
    public_base_url = (payload.api_base_url or "").strip() or None
    settings_bootstrap: dict[str, object] = {}
    if public_base_url:
        settings_bootstrap["api_base_url"] = public_base_url
    if smtp_bootstrap:
        settings_bootstrap.update(smtp_bootstrap)
    if settings_bootstrap:
        try:
            from app.schemas.settings import AppSettingsUpdate
            from app.services.settings_service import update_settings

            update_settings(db, AppSettingsUpdate(**settings_bootstrap), user_id=user.id)  # type: ignore[arg-type]
        except Exception as settings_exc:  # noqa: BLE001
            _logger.warning("OAuth bootstrap settings setup failed: %s", settings_exc)

    _set_onboarding_step(db, "finish")

    return BootstrapInitializeResponse(
        token=token,
        user=_to_profile(user),
        theme=BootstrapThemeResponse(preset=cfg.theme_preset or payload.theme_preset),
        vault_key=vault_key_plaintext,
        vault_key_warning=vault_key_plaintext is not None,
    )


def get_onboarding_or_fallback(db: Session) -> OnboardingStepResponse:
    """Return current and previous onboarding step; defaults to start/start if no row."""
    try:
        row = db.get(Onboarding, 1)
        if row:
            return OnboardingStepResponse(
                current_step=row.step,
                previous_step=row.previous_step,
            )
    except Exception:  # noqa: BLE001
        pass
    return OnboardingStepResponse(current_step="start", previous_step="start")


def set_onboarding_step(db: Session, step: str) -> OnboardingStepResponse:
    """Set onboarding step (and previous_step to current). Returns new state."""
    from app.schemas.auth import ONBOARDING_STEPS

    if step not in ONBOARDING_STEPS:
        raise HTTPException(status_code=400, detail=f"Invalid step: {step!r}")
    row = db.get(Onboarding, 1)
    if not row:
        row = Onboarding(id=1, step="start", previous_step="start")
        db.add(row)
    previous = row.step
    row.previous_step = previous
    row.step = step
    db.commit()
    db.refresh(row)
    return OnboardingStepResponse(current_step=row.step, previous_step=row.previous_step)


def _set_onboarding_step(db: Session, step: str) -> None:
    """Internal: set step without raising (e.g. after bootstrap)."""
    try:
        row = db.get(Onboarding, 1)
        if row:
            row.previous_step = row.step
            row.step = step
            db.commit()
        else:
            row = Onboarding(id=1, step=step, previous_step="summary")
            db.add(row)
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def login(
    db: Session,
    email: str,
    password_or_hash: str,
    cfg: AppSettings,
    ip_address: str | None = None,
    request: Any = None,
) -> AuthResponse:
    from app.services.log_service import write_log
    from app.services.user_service import record_failed_login, record_session, reset_login_attempts

    user = db.query(User).filter(User.email == email.strip().lower()).first()
    # Always call verify_password — even when user is None — to ensure constant-time
    # response and prevent timing-based email enumeration (L-08).
    _hash_to_check = user.hashed_password if user else _DUMMY_HASH
    _password_valid = verify_password(password_or_hash, _hash_to_check)

    # Task 3: Migrate existing legacy tokens (on first valid login with plaintext)
    if not _password_valid and user and not _is_client_hash(password_or_hash):
        from app.core.security import _DEFAULT_SALT, client_hash_password, get_client_salt

        current_salt = get_client_salt(db)
        if current_salt != _DEFAULT_SALT:
            # Check if login succeeds with the legacy hardcoded salt
            legacy_client_hash = client_hash_password(password_or_hash, _DEFAULT_SALT)
            if verify_password(legacy_client_hash, _hash_to_check):
                # SUCCESS with legacy salt! Migrate this user to the current dynamic salt.
                _logger.info("Migrating user %s to new CLIENT_HASH_SALT", user.email)
                new_client_hash = client_hash_password(password_or_hash, current_salt)
                user.hashed_password = hash_password(new_client_hash)
                db.commit()
                db.refresh(user)
                _password_valid = True

    if not user or not _password_valid:
        if user:
            record_failed_login(db, user, cfg)
        write_log(
            db=None,
            action="login_failed",
            entity_type="auth",
            entity_name=email.strip().lower(),
            severity="warn",
            category="auth",
            ip_address=ip_address,
            actor_name="anonymous",
            details=f"Failed login attempt for {email.strip().lower()!r}",
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Check lockout — return generic 401 to avoid username enumeration via 423
    if getattr(user, "locked_until", None) and user.locked_until and user.locked_until > utcnow():
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    reset_login_attempts(db, user)
    user.last_login = utcnow_iso()
    db.commit()
    db.refresh(user)

    write_log(
        db=None,
        action="login_success",
        entity_type="auth",
        entity_id=user.id,
        entity_name=user.display_name or user.email,
        severity="info",
        category="auth",
        ip_address=ip_address,
        actor_name=user.display_name or user.email,
        actor_id=user.id,
    )

    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


def get_me(db: Session, user_id: int) -> UserProfile:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _to_profile(user)


def _process_avatar(data: bytes) -> tuple[bytes, str]:
    """Validate, resize, and encode an avatar image (sync, safe to run in executor).

    Returns (processed_bytes, pillow_format_string).
    Raises on corrupt/unreadable images; resize failure falls back to original bytes.
    """
    import io

    from PIL import Image

    probe = Image.open(io.BytesIO(data))
    probe.verify()  # raises on corrupt or malicious files
    detected_format = probe.format or "PNG"

    try:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((256, 256))
        buf = io.BytesIO()
        img.save(buf, format=detected_format)
        return buf.getvalue(), detected_format
    except Exception:
        _logger.warning("Pillow resize failed; saving original photo as-is")
        return data, detected_format


async def update_profile(
    db: Session,
    user_id: int,
    display_name: str | None,
    profile_photo: UploadFile | None,
) -> UserProfile:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    changed_fields: list[str] = []

    if display_name is not None:
        user.display_name = display_name
        changed_fields.append("display_name")

    if profile_photo is not None:
        data = await profile_photo.read()
        if len(data) > _MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Profile photo must be ≤ 5 MB")

        # Validate actual file content — do NOT trust client Content-Type header.
        # Use native upload validation for primary MIME detection, Pillow for structural validation.
        import asyncio

        from app.core.upload_validation import infer_image_type_from_magic

        detected_mime = infer_image_type_from_magic(data[:2048])
        if detected_mime not in _ALLOWED_TYPES:
            raise HTTPException(
                status_code=422, detail=f"File type '{detected_mime}' is not allowed"
            )

        # Pillow verify + resize is CPU-bound (50–500 ms on large images); run in executor.
        try:
            loop = asyncio.get_running_loop()
            data, detected_format = await loop.run_in_executor(None, _process_avatar, data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="File is not a valid image") from exc

        detected_mime = _PILLOW_FORMAT_TO_MIME.get(detected_format or "", "")
        if detected_mime not in _ALLOWED_TYPES:
            raise HTTPException(
                status_code=422, detail=f"Image format {detected_format} is not allowed"
            )

        # Reject path traversal in client filename
        if profile_photo.filename and (
            "/" in profile_photo.filename or ".." in profile_photo.filename
        ):
            raise HTTPException(status_code=400, detail="Invalid profile photo filename")

        # Delete old photo
        if user.profile_photo:
            old_path = _PROFILES_DIR / user.profile_photo
            old_path.unlink(missing_ok=True)

        ext = _PILLOW_FORMAT_TO_EXT.get(detected_format or "", "jpg")
        safe_suffix = hashlib.sha256(data).hexdigest()[:12]
        filename = f"{user.id}-{safe_suffix}.{ext}"
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        out_path = (_PROFILES_DIR / filename).resolve()
        if not str(out_path).startswith(str(_PROFILES_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Invalid profile photo path")
        out_path.write_bytes(data)
        user.profile_photo = filename
        changed_fields.append("profile_photo")

    db.commit()
    db.refresh(user)

    if changed_fields:
        from app.services.log_service import write_log

        write_log(
            db=None,
            action="update_profile",
            entity_type="user",
            entity_id=user_id,
            entity_name=user.display_name or user.email,
            severity="info",
            category="auth",
            actor_name=user.display_name or user.email,
            actor_id=user_id,
            details=f"Updated fields: {', '.join(changed_fields)}",
        )

    return _to_profile(user)


def delete_account(db: Session, user_id: int) -> None:
    """Delete the authenticated user's account and clean up their profile photo."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    actor_name = user.display_name or user.email

    # Clean up profile photo file
    if user.profile_photo:
        photo_path = _PROFILES_DIR / user.profile_photo
        photo_path.unlink(missing_ok=True)

    db.delete(user)
    db.commit()

    from app.services.log_service import write_log

    write_log(
        db=None,
        action="delete_account",
        entity_type="user",
        entity_id=user_id,
        entity_name=actor_name,
        severity="info",
        category="auth",
        actor_name=actor_name,
        actor_id=user_id,
    )


def delete_user_permanent(db: Session, user_id: int, *, actor_id: int, actor_name: str) -> None:
    """Permanently remove a user (admin only). Cleans profile photo and deletes the user row."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    target_email = user.email
    target_name = user.display_name or user.email

    if user.profile_photo:
        photo_path = _PROFILES_DIR / user.profile_photo
        photo_path.unlink(missing_ok=True)

    db.delete(user)
    db.commit()

    from app.services.log_service import write_log

    write_log(
        db=None,
        action="user_removed_permanent",
        entity_type="user",
        entity_id=user_id,
        entity_name=target_name,
        severity="info",
        category="admin",
        actor_name=actor_name,
        actor_id=actor_id,
        details=json.dumps({"email": target_email}),
    )
