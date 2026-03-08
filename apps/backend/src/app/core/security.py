"""JWT, password hashing, Gravatar utilities, and FastAPI auth dependencies.

Preserves backward-compat dependencies (get_optional_user, require_write_auth,
require_auth_always) that existing routers rely on, while integrating with
FastAPI-Users for JWT validation and the CB_API_TOKEN legacy middleware.
"""

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
    return hashlib.md5(email.strip().lower().encode()).hexdigest()  # noqa: S324


# ---------------------------------------------------------------------------
# JWT helpers (used by bootstrap and legacy code paths)
# ---------------------------------------------------------------------------


def create_token(user_id: int, secret: str, timeout_hours: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": utcnow() + timedelta(hours=timeout_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> int | None:
    """Decode a legacy JWT and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependencies (backward-compat wrappers)
# ---------------------------------------------------------------------------


def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return None


def _is_legacy_admin(request: Request) -> bool:
    """Check if the LegacyTokenMiddleware flagged this request."""
    return getattr(request.state, "legacy_admin", False)


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> int | None:
    """Return the authenticated user_id, or None if absent/invalid.

    Returns 0 (service-account sentinel) when the request presents a valid
    CB_API_TOKEN bearer token.  Never raises.
    """
    if _is_legacy_admin(request):
        return 0

    from app.services.settings_service import get_or_create_settings

    raw_token = _extract_bearer(request)

    api_token = _get_api_token()
    if api_token and raw_token == api_token:
        return 0

    cfg = get_or_create_settings(db)

    if not api_token and (not cfg.auth_enabled or not cfg.jwt_secret):
        return None

    if not raw_token or not cfg.jwt_secret:
        return None

    from app.services.user_service import is_session_revoked

    if is_session_revoked(db, raw_token):
        return None

    # Try FastAPI-Users JWT format first (sub claim, with audience validation)
    try:
        payload = jwt.decode(
            raw_token, cfg.jwt_secret, algorithms=["HS256"], audience=["fastapi-users:auth"]
        )
        sub = payload.get("sub")
        if sub is not None:
            return int(sub)
    except (jwt.PyJWTError, ValueError, TypeError):
        pass

    # Fallback to legacy token format (no audience claim)
    try:
        payload = jwt.decode(
            raw_token, cfg.jwt_secret, algorithms=["HS256"], options={"verify_aud": False}
        )
        uid = payload.get("user_id")
        if uid is not None:
            return uid
    except (jwt.PyJWTError, ValueError, TypeError):
        pass

    return None


def require_write_auth(
    user_id: int | None = Depends(get_optional_user), db: Session = Depends(get_db)
) -> int | None:
    """Raise 401 when write access is not authorised."""
    from app.services.settings_service import get_or_create_settings

    cfg = get_or_create_settings(db)
    auth_required = cfg.auth_enabled or bool(_get_api_token())
    if auth_required and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def require_auth_always(user_id: int | None = Depends(get_optional_user)) -> int:
    """Validates JWT regardless of app_settings.auth_enabled."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
