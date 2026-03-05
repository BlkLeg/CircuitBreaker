"""JWT, password hashing, Gravatar utilities, and FastAPI auth dependencies."""
import hashlib
import logging
import os
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.session import get_db

_logger = logging.getLogger(__name__)


def _get_api_token() -> str | None:
    """Return the static CB_API_TOKEN from environment, or None if unset."""
    return os.getenv("CB_API_TOKEN") or None


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
        "exp": utcnow() + timedelta(hours=timeout_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> int | None:
    """Decode JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):]
    return None


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> int | None:
    """Return the authenticated user_id from JWT, or None if absent/invalid.

    Returns 0 (service-account sentinel) when the request presents a valid
    CB_API_TOKEN bearer token. Never raises — callers decide whether auth is
    required.
    """
    from app.services.settings_service import (
        get_or_create_settings,  # local import to avoid circular
    )

    raw_token = _extract_bearer(request)

    # CB_API_TOKEN takes priority over JWT — works regardless of auth_enabled
    api_token = _get_api_token()
    if api_token and raw_token == api_token:
        return 0  # sentinel: authenticated via static API token (no user row)

    cfg = get_or_create_settings(db)

    # When CB_API_TOKEN is set, JWTs are also a valid alternative — skip the
    # early-return so we fall through to JWT decoding below.
    if not api_token and (not cfg.auth_enabled or not cfg.jwt_secret):
        return None

    if not raw_token or not cfg.jwt_secret:
        return None

    return decode_token(raw_token, cfg.jwt_secret)


def require_write_auth(user_id: int | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> int | None:
    """Raise 401 when write access is not authorised.

    Write access is required when either ``auth_enabled`` is true *or*
    ``CB_API_TOKEN`` is set in the environment (i.e. the operator has opted
    into token-gated writes).  A ``user_id`` of 0 indicates API-token auth
    and is treated as authenticated.
    """
    from app.services.settings_service import (
        get_or_create_settings,  # local import to avoid circular
    )

    cfg = get_or_create_settings(db)
    auth_required = cfg.auth_enabled or bool(_get_api_token())
    if auth_required and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def require_auth_always(request: Request, user_id: int | None = Depends(get_optional_user)) -> int:
    """
    Validates JWT regardless of app_settings.auth_enabled.
    Used exclusively for scan-trigger endpoints.
    Raises HTTP 401 if token is missing or invalid.
    """
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
