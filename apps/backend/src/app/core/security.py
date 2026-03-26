"""JWT, password hashing, Gravatar utilities, and FastAPI auth dependencies.

Preserves backward-compat dependencies (get_optional_user, require_write_auth,
require_auth_always) that existing routers rely on, while integrating with
FastAPI-Users for JWT validation.  CB_API_TOKEN god-mode is deprecated;
rejection/rollback is handled by LegacyTokenMiddleware.
"""

import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import UTC, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.core.time import utcnow
from app.db.models import User
from app.db.session import get_db

_logger = logging.getLogger(__name__)

# Session validation cache: token_hash -> (user_id, expiry_ts).
# TTL 10s so revocation is effective quickly.
_SESSION_CACHE_TTL_S = 10
_session_cache: dict[str, tuple[int, float]] = {}
_session_cache_lock = threading.Lock()
_session_cache_max_size = 2000


def _hash_token_for_cache(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_api_token(raw_token: str, secret: str) -> str:
    """Legacy HMAC-SHA256(secret, raw_token).

    Only used for fallback verification of old unsalted hashes.
    """
    return hmac.new(secret.encode(), raw_token.encode(), hashlib.sha256).hexdigest()


def create_salted_api_token_hash(raw_token: str) -> str:
    """Create a per-token salted HMAC hash stored as '{salt_hex}:{hmac_hex}'.

    The salt is 32 random bytes (os.urandom), HMAC uses SHA-256.
    Verification requires iterating stored tokens (no direct lookup) since
    the salt is embedded in the stored value.
    """
    salt = os.urandom(32)
    token_hmac = hmac.new(salt, raw_token.encode(), hashlib.sha256).hexdigest()
    return f"{salt.hex()}:{token_hmac}"


def verify_salted_api_token_hash(raw_token: str, stored: str) -> bool:
    """Verify a raw token against a salted stored hash ('{salt_hex}:{hmac_hex}').

    Returns False for legacy unsalted hashes (no ':' prefix with 64-char salt hex).
    """
    if ":" not in stored:
        return False
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt_hex, stored_hmac = parts
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    computed = hmac.new(salt, raw_token.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, stored_hmac)


def _session_cache_get(token_hash: str) -> int | None:
    now = time.monotonic()
    with _session_cache_lock:
        entry = _session_cache.get(token_hash)
        if entry is None:
            return None
        user_id, expiry = entry
        if expiry <= now:
            _session_cache.pop(token_hash, None)
            return None
        return user_id


def _session_cache_set(token_hash: str, user_id: int) -> None:
    now = time.monotonic()
    expiry = now + _SESSION_CACHE_TTL_S
    with _session_cache_lock:
        if len(_session_cache) >= _session_cache_max_size:
            to_drop = sorted(_session_cache.items(), key=lambda x: x[1][1])[
                : _session_cache_max_size // 2
            ]
            for k, _ in to_drop:
                _session_cache.pop(k, None)
        _session_cache[token_hash] = (user_id, expiry)


def invalidate_session_cache(token: str | None = None) -> None:
    """Invalidate session validation cache. Call when a session is revoked.

    If token is provided, only that token's entry is removed. If token is None,
    the entire cache is cleared (use when revoking by session_id or user_id).
    """
    with _session_cache_lock:
        if token is not None:
            _session_cache.pop(_hash_token_for_cache(token), None)
        else:
            _session_cache.clear()


def _log_api_token_deprecation() -> None:
    """Emit a one-shot deprecation warning if CB_API_TOKEN is still set."""
    if os.getenv("CB_API_TOKEN"):
        _logger.warning(
            "DEPRECATION: CB_API_TOKEN is deprecated and will be removed in v0.4.0. "
            "Migrate to service accounts (POST /api/v1/auth/service-account)."
        )


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

# Must match frontend CIRCUIT_BREAKER_SALT so client-hashed login works.
# In v0.3.0+ this defaults to a dynamic value if CB_CLIENT_SALT is set.
_DEFAULT_SALT = "circuitbreaker-salt-v1"
CLIENT_HASH_SALT = os.getenv("CB_CLIENT_SALT", _DEFAULT_SALT)


def get_client_salt(db: Session | None = None) -> str:
    """Return the active client-side hashing salt.

    Priority: CB_CLIENT_SALT env > app_settings.client_hash_salt > hardcoded default.
    """
    env_salt = os.getenv("CB_CLIENT_SALT")
    if env_salt:
        return env_salt

    if db:
        from app.services.settings_service import get_or_create_settings

        cfg = get_or_create_settings(db)
        if cfg.client_hash_salt:
            return cfg.client_hash_salt

    return _DEFAULT_SALT


def client_hash_password(plain: str, salt: str | None = None) -> str:
    """SHA256(plain + salt) hex. Use when storing a password that will be
    sent by the client as password_hash on login (e.g. local user temp password).
    """
    active_salt = salt or CLIENT_HASH_SALT
    return hashlib.sha256((plain + active_salt).encode()).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Gravatar
# ---------------------------------------------------------------------------


def gravatar_hash(email: str) -> str:
    # MD5 is required by the Gravatar protocol and is intentionally limited to this helper.
    return hashlib.md5(email.strip().lower().encode(), usedforsecurity=False).hexdigest()  # noqa: S324


# ---------------------------------------------------------------------------
# JWT helpers (used by bootstrap and legacy code paths)
# ---------------------------------------------------------------------------


# Audience for session JWTs; required so password-reset/MFA tokens are not accepted as sessions.
SESSION_AUDIENCE = "fastapi-users:auth"


def create_token(
    user_id: int,
    secret: str,
    timeout_hours: int | None,
    *,
    role: str | None = None,
    scopes: list[str] | None = None,
    demo_expires: str | None = None,
    extra_claims: dict | None = None,
) -> str:
    payload = {
        "user_id": user_id,
        "exp": utcnow() + timedelta(hours=timeout_hours or 24),
        "aud": SESSION_AUDIENCE,
    }
    if role:
        payload["role"] = role
    if scopes is not None:
        payload["scopes"] = scopes
    if demo_expires:
        payload["demo_expires"] = demo_expires
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> int | None:
    """Decode a session JWT (with audience) and return user_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], audience=[SESSION_AUDIENCE])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str, secret: str | None = None) -> dict[str, Any]:
    """Decode a JWT and return its claim payload.

    When ``secret`` is supplied, full verification is performed (HS256 signature,
    expiry, and audience).  This is the preferred and secure code path.

    When ``secret`` is ``None``, signature verification is skipped as a last-resort
    fallback (e.g. app not yet bootstrapped and jwt_secret unavailable).  In that
    case the returned dict is restricted to only the ``tenant_id`` claim so that
    no security-sensitive claims leak through the unverified path.
    Do NOT use this function as an authentication gate under any circumstances.
    """
    try:
        if secret:
            return jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=[SESSION_AUDIENCE],
            )
        # Unverified fallback: secret unavailable (e.g. pre-bootstrap). Caller must
        # NEVER use the result for auth/authz decisions.
        raw = jwt.decode(  # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode  # noqa: E501
            token,
            options={"verify_signature": False},
            algorithms=[
                "HS256"
            ],  # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode  # noqa: E501
        )
        # Expose only tenant_id — all other claims are suppressed on unverified path.
        return {"tenant_id": raw.get("tenant_id")} if raw else {}
    except jwt.PyJWTError:
        return {}


# ---------------------------------------------------------------------------
# FastAPI dependencies (backward-compat wrappers)
# ---------------------------------------------------------------------------


def _extract_bearer(request: HTTPConnection) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return None


def _extract_token(request: HTTPConnection) -> str | None:
    """Token from Authorization header or cb_session cookie (httpOnly)."""
    token = _extract_bearer(request)
    if token:
        return token
    from app.core.auth_cookie import COOKIE_NAME

    return request.cookies.get(COOKIE_NAME)


def _is_legacy_admin(request: HTTPConnection) -> bool:
    """Check if the LegacyTokenMiddleware flagged this request."""
    return getattr(request.state, "legacy_admin", False)


def _is_user_accessible(db: Session, user_id: int) -> bool:
    if user_id == 0:
        return True  # Sentinel for service account / legacy admin
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return False
    if user.locked_until and user.locked_until > utcnow():
        return False
    if user.role == "demo" and user.demo_expires:
        expiry = user.demo_expires
        if getattr(expiry, "tzinfo", None) is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry <= utcnow():
            return False
    return True


async def get_optional_user(request: HTTPConnection, db: Session = Depends(get_db)) -> int | None:
    """Return the authenticated user_id, or None if absent/invalid.

    Returns 0 (service-account sentinel) when the LegacyTokenMiddleware
    has flagged the request (CB_LEGACY_AUTH rollback).  Never raises.
    """
    if _is_legacy_admin(request):
        return 0

    from app.services.settings_service import get_or_create_settings

    raw_token = _extract_token(request)

    cfg = get_or_create_settings(db)

    if not cfg.auth_enabled:
        return 0  # App not bootstrapped / auth disabled — open access

    if not cfg.jwt_secret:
        return None

    if not raw_token:
        return None

    token_hash = _hash_token_for_cache(raw_token)
    cached_uid = _session_cache_get(token_hash)
    if cached_uid is not None:
        return cached_uid

    from app.services.user_service import is_session_revoked

    if is_session_revoked(db, raw_token):
        return None

    # Session JWT: FastAPI-Users format (sub) or CB session format (user_id), both with audience
    try:
        payload = jwt.decode(
            raw_token, cfg.jwt_secret, algorithms=["HS256"], audience=[SESSION_AUDIENCE]
        )
        sub = payload.get("sub")
        if sub is not None:
            uid = int(sub)
            if _is_user_accessible(db, uid):
                _session_cache_set(token_hash, uid)
                return uid
            return None
        uid_raw = payload.get("user_id")
        if uid_raw is not None:
            uid_int = int(uid_raw)
            if _is_user_accessible(db, uid_int):
                _session_cache_set(token_hash, uid_int)
                return uid_int
            return None
    except (jwt.PyJWTError, ValueError, TypeError):
        pass

    # Static API token (machine–machine): scan with per-token salted HMAC verification.
    # Linear scan is acceptable since admin-created API tokens are few (<100 typical).
    from app.db.models import APIToken

    api_token_row = None
    for candidate in db.query(APIToken).all():
        stored = candidate.token_hash or ""
        if verify_salted_api_token_hash(raw_token, stored):
            api_token_row = candidate
            break
    if api_token_row:
        if api_token_row.expires_at and api_token_row.expires_at <= utcnow():
            return None
        uid = api_token_row.created_by
        if _is_user_accessible(db, uid):
            _session_cache_set(token_hash, uid)
            return uid
        return None

    return None


async def require_write_auth(
    user_id: int | None = Depends(get_optional_user), db: Session = Depends(get_db)
) -> int | None:
    """Raise 401/403 when write access is not authorised."""
    from app.core.rbac import _effective_role, effective_scopes, has_scope

    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_id == 0:
        return user_id
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not _is_user_accessible(db, user_id):
        raise HTTPException(status_code=403, detail="Account is not accessible")
    role = _effective_role(user)
    scopes = effective_scopes(user)
    if role not in {"admin", "editor"} and not has_scope(scopes, "write", "*"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user_id


async def require_auth_always(
    user_id: int | None = Depends(get_optional_user), db: Session = Depends(get_db)
) -> int:
    """Validates JWT and raises 401 if no authenticated user."""
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_id != 0 and not _is_user_accessible(db, user_id):
        raise HTTPException(status_code=403, detail="Account is not accessible")
    return user_id


# Alias for backward-compat and global router enforcement
require_auth = require_auth_always
