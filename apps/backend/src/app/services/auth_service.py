"""Auth business logic: register, login, profile management."""

import json
import logging
import re
import secrets as _secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_token, gravatar_hash, hash_password, verify_password
from app.core.time import utcnow, utcnow_iso
from app.db.models import AppSettings, Log, User
from app.schemas.auth import (
    AuthResponse,
    BootstrapInitializeResponse,
    BootstrapStatusResponse,
    BootstrapThemeResponse,
    UserProfile,
)

_logger = logging.getLogger(__name__)

from app.core.config import settings as _settings  # noqa: E402

_PROFILES_DIR = Path(_settings.uploads_dir) / "profiles"
_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Hard limits applied before any regex to prevent polynomial backtracking on
# arbitrarily large user-supplied strings (ReDoS mitigation).
_MAX_EMAIL_LEN = 254  # RFC 5321 maximum
_MAX_PASSWORD_LEN = 1024


def _to_profile(user: User) -> UserProfile:
    photo_url = f"/uploads/profiles/{user.profile_photo}" if user.profile_photo else None
    role = getattr(user, "role", None) or ("admin" if user.is_admin else "viewer")
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gravatar_hash=user.gravatar_hash,
        is_admin=user.is_admin,
        is_superuser=user.is_superuser,
        language=user.language or "en",
        profile_photo_url=photo_url,
        role=role,
    )


def _make_token(user: User, cfg: AppSettings) -> str:
    return create_token(user.id, cfg.jwt_secret, cfg.session_timeout_hours)  # type: ignore[arg-type]


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
    if not smtp_enabled:
        return None

    host = (smtp_host or "").strip()
    from_email = (smtp_from_email or "").strip().lower()
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
    new_password: str,
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

    if len(new_password) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    _validate_password(new_password)

    revoke_all_sessions(db, user.id)

    user.hashed_password = hash_password(new_password)
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
    new_password: str,
    cfg: AppSettings,
    *,
    request=None,
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
        db, user, new_password, source="vault_key", update_last_login=auto_login
    )

    if not auto_login:
        return user

    token = _make_token(user, cfg)
    record_session(db, user, request, token, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


def register(
    db: Session,
    email: str,
    password: str,
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
    if len(password) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    _validate_password(password)

    is_first_user = db.query(User).count() == 0

    now = utcnow_iso()
    user = User(
        email=email.strip().lower(),
        hashed_password=hash_password(password),
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
    user_count = db.query(User).count()
    cfg = db.query(AppSettings).first()
    # Use jwt_secret as the bootstrap-completion indicator: it is set during
    # bootstrap_initialize and is NULL on any uninitialized system, even if
    # stale user rows exist from a pre-OOBE development database.
    needs_bootstrap = cfg is None or not bool(cfg.jwt_secret)
    return BootstrapStatusResponse(needs_bootstrap=needs_bootstrap, user_count=user_count)


def _derive_display_name(email: str, display_name: str | None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    local = email.strip().lower().split("@")[0]
    cleaned = re.sub(r"[._\-]+", " ", local).strip()
    if not cleaned:
        return "Admin"
    return " ".join(part.capitalize() for part in cleaned.split())


def bootstrap_initialize(
    db: Session,
    cfg: AppSettings,
    email: str,
    password: str,
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
    if len(password) > _MAX_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail="Password is too long")
    _validate_password(password)
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

    try:
        db.execute(text("BEGIN IMMEDIATE"))
    except Exception:
        # Non-SQLite engines (e.g. PostgreSQL) don't support BEGIN IMMEDIATE.
        # Roll back to clear the aborted transaction state before continuing.
        db.rollback()

    # If jwt_secret is already set, bootstrap was previously completed — reject.
    if bool(cfg.jwt_secret):
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Bootstrap already completed. Please refresh and log in.",
        )

    # Clean up any stale users that exist from a pre-OOBE development database
    # (users created before the bootstrap flow was introduced, without auth configured).
    stale_count = db.query(User).count()
    if stale_count > 0:
        db.query(User).delete()
        db.flush()

    now = utcnow_iso()
    user = User(
        email=email_norm,
        hashed_password=hash_password(password),
        gravatar_hash=gravatar_hash(email_norm),
        display_name=_derive_display_name(email_norm, display_name),
        language=language or "en",
        is_admin=True,
        is_superuser=True,
        is_active=True,
        created_at=now,
        role="admin",
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
    vault_key_plaintext: str | None = None
    try:
        from app.services import vault_service
        from app.services.credential_vault import get_vault

        new_key = vault_service.generate_vault_key()
        vault_service.write_vault_key_to_env(new_key)

        # Persist the key and its hash into AppSettings as a DB fallback
        import hashlib
        import os

        cfg_fresh = db.get(AppSettings, 1)
        if cfg_fresh:
            cfg_fresh.vault_key = new_key
            cfg_fresh.vault_key_hash = hashlib.sha256(new_key.encode()).hexdigest()
            cfg_fresh.vault_key_rotated_at = utcnow()
            db.commit()

        # Inject into process env so the singleton is immediately usable
        os.environ["CB_VAULT_KEY"] = new_key
        get_vault().reinitialize(new_key)

        vault_key_plaintext = new_key
        _logger.info("Vault key generated and stored during OOBE bootstrap.")
    except Exception as _ve:  # noqa: BLE001
        _logger.warning("Vault key generation during OOBE failed: %s", _ve)

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

    return BootstrapInitializeResponse(
        token=token,
        user=_to_profile(user),
        theme=BootstrapThemeResponse(preset=cfg.theme_preset or theme_preset),
        vault_key=vault_key_plaintext,
        vault_key_warning=vault_key_plaintext is not None,
    )


def login(
    db: Session,
    email: str,
    password: str,
    cfg: AppSettings,
    ip_address: str | None = None,
    request=None,
) -> AuthResponse:
    from app.services.log_service import write_log
    from app.services.user_service import record_failed_login, record_session, reset_login_attempts

    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.hashed_password):
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

    # Check lockout (Phase 6.5)
    if getattr(user, "locked_until", None) and user.locked_until and user.locked_until > utcnow():
        raise HTTPException(
            status_code=423,
            detail="Account locked due to failed login attempts. Contact an administrator.",
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
        if profile_photo.content_type not in _ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="Profile photo must be JPEG or PNG")

        data = await profile_photo.read()
        if len(data) > _MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Profile photo must be ≤ 10 MB")

        # Optional: resize with Pillow
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(data))
            img.thumbnail((256, 256))
            buf = io.BytesIO()
            fmt = "JPEG" if profile_photo.content_type == "image/jpeg" else "PNG"
            img.save(buf, format=fmt)
            data = buf.getvalue()
        except Exception:
            _logger.warning("Pillow resize failed; saving original photo as-is")

        # Delete old photo
        if user.profile_photo:
            old_path = _PROFILES_DIR / user.profile_photo
            old_path.unlink(missing_ok=True)

        ext = "jpg" if profile_photo.content_type == "image/jpeg" else "png"
        filename = f"{user.id}-{profile_photo.filename or 'photo.' + ext}"
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        ((_PROFILES_DIR) / filename).write_bytes(data)
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
