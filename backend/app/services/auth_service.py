"""Auth business logic: register, login, profile management."""
import logging
import re
import secrets as _secrets
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.security import create_token, gravatar_hash, hash_password, verify_password
from app.db.models import AppSettings, Log, User
from app.schemas.auth import AuthResponse, BootstrapInitializeResponse, BootstrapStatusResponse, UserProfile, BootstrapThemeResponse

_logger = logging.getLogger(__name__)

from app.core.config import settings as _settings  # noqa: E402
_PROFILES_DIR = Path(_settings.uploads_dir) / "profiles"
_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _to_profile(user: User) -> UserProfile:
    photo_url = f"/uploads/profiles/{user.profile_photo}" if user.profile_photo else None
    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        gravatar_hash=user.gravatar_hash,
        is_admin=user.is_admin,
        profile_photo_url=photo_url,
    )


def _make_token(user: User, cfg: AppSettings) -> str:
    return create_token(user.id, cfg.jwt_secret, cfg.session_timeout_hours)


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


def register(
    db: Session,
    email: str,
    password: str,
    cfg: AppSettings,
    display_name: Optional[str] = None,
) -> AuthResponse:
    if db.query(User).count() == 0:
        raise HTTPException(
            status_code=409,
            detail="Bootstrap required. Use /api/v1/bootstrap/initialize for first account setup.",
        )

    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    _validate_password(password)

    # First user becomes admin
    is_admin = db.query(User).count() == 0

    now = datetime.now(timezone.utc).isoformat()
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        gravatar_hash=gravatar_hash(email),
        display_name=display_name.strip() if display_name and display_name.strip() else email.split("@")[0],
        is_admin=is_admin,
        created_at=now,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    # Auto-generate jwt_secret if not yet set (user is registering before enabling auth in settings)
    if not cfg.jwt_secret:
        cfg.jwt_secret = _secrets.token_hex(32)
        db.commit()

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


def _derive_display_name(email: str, display_name: Optional[str]) -> str:
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
    display_name: Optional[str] = None,
) -> BootstrapInitializeResponse:
    email_norm = email.strip().lower()
    if not _EMAIL_RE.match(email_norm):
        raise HTTPException(status_code=400, detail="Invalid email address")
    _validate_password(password)

    try:
        db.execute(text("BEGIN IMMEDIATE"))
    except Exception:
        # Non-SQLite engines may not support BEGIN IMMEDIATE; continue with normal transaction semantics.
        pass

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

    now = datetime.now(timezone.utc).isoformat()
    user = User(
        email=email_norm,
        password_hash=hash_password(password),
        gravatar_hash=gravatar_hash(email_norm),
        display_name=_derive_display_name(email_norm, display_name),
        is_admin=True,
        created_at=now,
    )
    db.add(user)

    cfg.auth_enabled = True
    cfg.theme_preset = theme_preset
    if not cfg.jwt_secret:
        cfg.jwt_secret = _secrets.token_hex(32)

    audit_log = Log(
        timestamp=datetime.now(timezone.utc),
        level="info",
        category="bootstrap",
        action="bootstrap_create_user",
        actor="system",
        actor_gravatar_hash=gravatar_hash(email_norm),
        entity_type="user",
        details=json.dumps({"email": email_norm, "theme_preset": theme_preset}),
        status_code=200,
    )
    db.add(audit_log)

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    token = _make_token(user, cfg)
    return BootstrapInitializeResponse(
        token=token,
        user=_to_profile(user),
        theme=BootstrapThemeResponse(preset=cfg.theme_preset or theme_preset),
    )


def login(db: Session, email: str, password: str, cfg: AppSettings) -> AuthResponse:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(user)

    token = _make_token(user, cfg)
    return AuthResponse(token=token, user=_to_profile(user))


def get_me(db: Session, user_id: int) -> UserProfile:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return _to_profile(user)


async def update_profile(
    db: Session,
    user_id: int,
    display_name: Optional[str],
    profile_photo: Optional[UploadFile],
) -> UserProfile:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if display_name is not None:
        user.display_name = display_name

    if profile_photo is not None:
        if profile_photo.content_type not in _ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="Profile photo must be JPEG or PNG")

        data = await profile_photo.read()
        if len(data) > _MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Profile photo must be ≤ 10 MB")

        # Optional: resize with Pillow
        try:
            from PIL import Image
            import io
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

    db.commit()
    db.refresh(user)
    return _to_profile(user)


def delete_account(db: Session, user_id: int) -> None:
    """Delete the authenticated user's account and clean up their profile photo."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Clean up profile photo file
    if user.profile_photo:
        photo_path = _PROFILES_DIR / user.profile_photo
        photo_path.unlink(missing_ok=True)

    db.delete(user)
    db.commit()

