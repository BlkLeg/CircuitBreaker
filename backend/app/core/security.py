"""JWT, password hashing, Gravatar utilities, and FastAPI auth dependencies."""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Gravatar
# ---------------------------------------------------------------------------

def gravatar_hash(email: str) -> str:
    """MD5 of lowercased/trimmed email — used as Gravatar identifier."""
    return hashlib.md5(email.strip().lower().encode()).hexdigest()  # noqa: S324


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(user_id: int, secret: str, timeout_hours: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=timeout_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> Optional[int]:
    """Decode JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return None


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[int]:
    """Return the authenticated user_id from JWT, or None if absent/invalid.

    This dependency never raises — callers decide whether auth is required.
    """
    from app.services.settings_service import get_or_create_settings  # local import to avoid circular

    cfg = get_or_create_settings(db)
    if not cfg.auth_enabled or not cfg.jwt_secret:
        return None

    token = _extract_bearer(request)
    if not token:
        return None

    return decode_token(token, cfg.jwt_secret)


def require_write_auth(user_id: Optional[int] = Depends(get_optional_user), db: Session = Depends(get_db)) -> Optional[int]:
    """Raise 401 when auth is enabled and the request carries no valid JWT."""
    from app.services.settings_service import get_or_create_settings  # local import to avoid circular

    cfg = get_or_create_settings(db)
    if cfg.auth_enabled and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
