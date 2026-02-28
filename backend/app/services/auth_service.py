"""Auth business logic: register, login, profile management."""
import logging
import re
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_token, gravatar_hash, hash_password, verify_password
from app.db.models import AppSettings, User
from app.schemas.auth import AuthResponse, UserProfile

_logger = logging.getLogger(__name__)
_PROFILES_DIR = Path("data/uploads/profiles")
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
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


def register(
    db: Session,
    email: str,
    password: str,
    cfg: AppSettings,
    display_name: Optional[str] = None,
) -> AuthResponse:
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    now = datetime.now(timezone.utc).isoformat()
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        gravatar_hash=gravatar_hash(email),
        display_name=display_name.strip() if display_name and display_name.strip() else email.split("@")[0],
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
            raise HTTPException(status_code=413, detail="Profile photo must be ≤ 5 MB")

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

