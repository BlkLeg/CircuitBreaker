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

from app.core.constants import CLIENT_HASH_PBKDF2_ITERATIONS, CLIENT_HASH_V2_PREFIX
from app.core.time import utcnow
from app.db.models import User
from app.db.session import get_db

_logger = logging.getLogger(__name__)

# Session validation cache: token_hash -> (user_id, expiry_ts).
# TTL 10s so revocation is effective quickly.
_SESSION_CACHE_TTL_S = 10
_session_cache: dict[str, tuple[int, float, tuple[str, ...] | None]] = {}
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


def _normalise_token_scopes(raw_scopes: object) -> tuple[str, ...] | None:
    if raw_scopes is None:
        return None
    if not isinstance(raw_scopes, list):
        return ()
    return tuple(str(scope).strip() for scope in raw_scopes if str(scope).strip())


def _set_request_token_scopes(request: HTTPConnection, scopes: tuple[str, ...] | None) -> None:
    if scopes is None:
        if hasattr(request.state, "token_scopes"):
            delattr(request.state, "token_scopes")
        return
    request.state.token_scopes = scopes


# ── Cross-worker cache coherence ─────────────────────────────────────────────
#
# The app ships behind `uvicorn --workers 2`, so the per-process cache alone
# meant a logout handled by worker A left worker B honouring the same token
# until its own entry aged out. Revocations are therefore also written to Redis,
# which every worker shares, and a cache hit is confirmed against it before it
# is trusted. Redis unreachable ⇒ the cache is bypassed and the caller does the
# full database validation, so the degraded mode is slow rather than stale.

_REVOKED_KEY_PREFIX = "cb:sess:revoked:"
_FLUSH_EPOCH_KEY = "cb:sess:flush-epoch"
# Comfortably longer than the cache TTL: once no cached entry can survive, the
# marker has nothing left to invalidate and Redis can expire it.
_REVOKED_MARKER_TTL_S = _SESSION_CACHE_TTL_S * 6

_local_flush_epoch: str | None = None


def _shared_cache_state(token_hash: str) -> tuple[bool, bool, str | None]:
    """Return (reachable, token_revoked, flush_epoch) from the shared store."""
    from app.core.redis import get_sync_redis, reset_sync_redis

    client = get_sync_redis()
    if client is None:
        return False, False, None
    try:
        epoch, revoked = client.mget(_FLUSH_EPOCH_KEY, f"{_REVOKED_KEY_PREFIX}{token_hash}")
    except Exception:
        reset_sync_redis()
        return False, False, None
    return True, revoked is not None, epoch


def _session_cache_get(token_hash: str) -> tuple[int, tuple[str, ...] | None] | None:
    global _local_flush_epoch
    now = time.monotonic()
    with _session_cache_lock:
        entry = _session_cache.get(token_hash)
        if entry is None:
            return None
        user_id, expiry, scopes = entry
        if expiry <= now:
            _session_cache.pop(token_hash, None)
            return None

    reachable, revoked, epoch = _shared_cache_state(token_hash)
    if not reachable:
        # Cannot prove the entry is still valid — fall through to the database
        # rather than serve a decision another worker may already have revoked.
        return None
    if revoked:
        with _session_cache_lock:
            _session_cache.pop(token_hash, None)
        return None
    if epoch != _local_flush_epoch:
        # Another worker cleared every session (password change, bulk revoke).
        _local_flush_epoch = epoch
        with _session_cache_lock:
            _session_cache.clear()
        return None

    return user_id, scopes


def _session_cache_set(
    token_hash: str, user_id: int, scopes: tuple[str, ...] | None = None
) -> None:
    now = time.monotonic()
    expiry = now + _SESSION_CACHE_TTL_S
    with _session_cache_lock:
        if len(_session_cache) >= _session_cache_max_size:
            to_drop = sorted(_session_cache.items(), key=lambda x: x[1][1])[
                : _session_cache_max_size // 2
            ]
            for k, _ in to_drop:
                _session_cache.pop(k, None)
        _session_cache[token_hash] = (user_id, expiry, scopes)


def invalidate_token_cache() -> None:
    """Drop every cached token resolution.

    Called when a token is rotated or revoked. Coarse on purpose: the cache is
    keyed by a hash of the raw secret, which the rotation path does not have
    for the token it is retiring, and a token cache is small enough that
    rebuilding it costs far less than a revoked credential that still works.
    """
    with _session_cache_lock:
        _session_cache.clear()


def invalidate_session_cache(token: str | None = None) -> None:
    """Invalidate session validation cache. Call when a session is revoked.

    If token is provided, only that token's entry is removed. If token is None,
    the entire cache is cleared (use when revoking by session_id or user_id).

    The invalidation is also recorded in Redis so the other uvicorn workers stop
    honouring the same token; see the cross-worker note above. A Redis failure
    here is logged and swallowed — the local cache is still cleared, and the
    read path bypasses the cache entirely while Redis is unreachable, so the
    result is a correct-but-slower validation rather than a stale session.
    """
    with _session_cache_lock:
        if token is not None:
            _session_cache.pop(_hash_token_for_cache(token), None)
        else:
            _session_cache.clear()

    from app.core.redis import get_sync_redis, reset_sync_redis

    client = get_sync_redis()
    if client is None:
        return
    try:
        if token is not None:
            client.setex(
                f"{_REVOKED_KEY_PREFIX}{_hash_token_for_cache(token)}",
                _REVOKED_MARKER_TTL_S,
                "1",
            )
        else:
            client.incr(_FLUSH_EPOCH_KEY)
    except Exception:
        _logger.warning(
            "Could not publish session invalidation to Redis; other workers will "
            "fall back to database validation",
            exc_info=True,
        )
        reset_sync_redis()


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


def legacy_client_wire_hash_v1(plain: str, salt: str) -> str:
    """Deprecated v1 wire hash: SHA256(plain + salt) hex.

    Retained for login verification when stored bcrypt was derived from the old
    browser format. New credentials use :func:`client_hash_password` (PBKDF2).
    """
    # codeql[py/weak-sensitive-data-hashing]: v1 wire compatibility only; v2 is PBKDF2.
    return hashlib.sha256((plain + salt).encode()).hexdigest()


def client_hash_password(plain: str, salt: str | None = None) -> str:
    """PBKDF2-HMAC-SHA256 hex, prefixed for version detection.

    Matches the browser :func:`hashPasswordForAuth` output. The result is bcrypt'd
    again server-side for storage.
    """
    active_salt = salt or get_client_salt()
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        active_salt.encode("utf-8"),
        CLIENT_HASH_PBKDF2_ITERATIONS,
        dklen=32,
    )
    return f"{CLIENT_HASH_V2_PREFIX}{dk.hex()}"


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
    timeout_hours: float | int | None,
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
    # Callers that need every mint to be distinct — rotating a service account —
    # pass a `jti` through extra_claims. Without one, two tokens minted in the same
    # second with the same claims are byte-identical, which makes "rotate" a no-op.
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


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """Decode a JWT and return its claim payload.

    Full verification is always performed (HS256 signature, expiry, and audience).
    Callers must not decode claims when the signing secret is unavailable.
    """
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=[SESSION_AUDIENCE],
        )
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


#: Routes that may act as the admin sentinel while the app is unbootstrapped.
#:
#: Before the first admin exists there is nobody to authenticate, so first-run
#: has to run as *something*. It used to run as an admin on every route, which
#: meant anyone who could reach the port during the setup window could rewrite
#: settings and OAuth providers — and so hand themselves the operator's account
#: at the moment it was created. The setup token (SEC-09) guarded only the
#: account creation itself, not the configuration around it.
#:
#: This is the surface the OOBE wizard actually touches before it flips
#: `auth_enabled`: the bootstrap endpoints (themselves setup-token gated), the
#: auth routes, the settings read that renders the wizard, and the OAuth write
#: the provider step performs before an account can exist. Everything else —
#: inventory, monitors, agents, admin, uploads, docs — answers 401 until an
#: admin exists, which is what it would have done anyway had auth been on.
#:
#: `(prefix, methods)`; `methods` of None means any method.
_PRE_BOOTSTRAP_SETUP_SURFACE: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("/api/v1/bootstrap", None),
    ("/api/v1/auth", None),
    ("/api/v1/settings/oauth", frozenset({"PATCH"})),
    ("/api/v1/settings", frozenset({"GET", "HEAD"})),
)


def _is_pre_bootstrap_setup_surface(request: HTTPConnection) -> bool:
    """Whether this unbootstrapped request is part of first-run setup."""
    path = request.scope.get("path", "")
    # WebSocket connections carry no method; treat them as a read for matching.
    method = str(request.scope.get("method", "GET")).upper()
    for prefix, methods in _PRE_BOOTSTRAP_SETUP_SURFACE:
        if path == prefix or path.startswith(f"{prefix}/"):
            if methods is None or method in methods:
                return True
    return False


def service_account_token_is_live(db: Session, raw_token: str) -> bool:
    """True when `raw_token` still matches an unexpired APIToken row.

    `create_service_account` stores a salted hash of the JWT it mints "for tracking
    and revocation"; this is the read that makes the second half of that true. The
    row's own `expires_at` is honoured as well as the JWT's `exp`, so shortening a
    token's life through the row takes effect immediately.
    """
    from app.db.models import APIToken

    for candidate in db.query(APIToken).all():
        if verify_salted_api_token_hash(raw_token, candidate.token_hash or ""):
            if candidate.expires_at and candidate.expires_at <= utcnow():
                return False
            return True
    return False


def resolve_optional_user_id_sync(db: Session, request: HTTPConnection) -> int | None:
    """Return the authenticated user_id, or None if absent/invalid (synchronous).

    Same logic as :func:`get_optional_user` for use from sync middleware.
    Returns 0 when LegacyTokenMiddleware granted legacy admin, or when the app
    is unbootstrapped and the request is part of the first-run setup surface.
    """
    _set_request_token_scopes(request, None)
    if _is_legacy_admin(request):
        return 0

    from app.services.settings_service import get_or_create_settings

    raw_token = _extract_token(request)

    cfg = get_or_create_settings(db)

    if not cfg.auth_enabled:
        # App not bootstrapped. The admin-equivalent sentinel is handed out only
        # to the routes first-run genuinely needs — see _PRE_BOOTSTRAP_SETUP_SURFACE.
        if _is_pre_bootstrap_setup_surface(request):
            return 0
        return None

    if not cfg.jwt_secret:
        return None

    if not raw_token:
        return None

    token_hash = _hash_token_for_cache(raw_token)
    cached = _session_cache_get(token_hash)
    if cached is not None:
        cached_uid, cached_scopes = cached
        _set_request_token_scopes(request, cached_scopes)
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
            if uid_int == 0:
                # A service-account JWT is live only while its APIToken row is.
                # `_is_user_accessible` returns True unconditionally for the
                # sentinel, so without this the JWT authenticated on signature
                # alone: revoking the row, or rotating it, left the credential
                # working until its own `exp` — a year by default.
                #
                # The scan verifies rather than looks up, because the salt is
                # per-token random. It costs the same scan opaque tokens already
                # pay, and only on a cache miss: `_session_cache` holds the
                # answer for 10s and `invalidate_token_cache()` runs on revoke
                # and rotate, so a withdrawal is visible within that window.
                if not service_account_token_is_live(db, raw_token):
                    return None
                token_scopes = _normalise_token_scopes(payload.get("scopes"))
                _session_cache_set(token_hash, 0, token_scopes)
                _set_request_token_scopes(request, token_scopes)
                return 0
            if _is_user_accessible(db, uid_int):
                _session_cache_set(token_hash, uid_int, None)
                _set_request_token_scopes(request, None)
                return uid_int
            return None
    except (jwt.PyJWTError, ValueError, TypeError):
        pass

    # Static API token (machine–machine): scan with per-token salted HMAC verification.
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
            token_scopes = _normalise_token_scopes(api_token_row.scopes)
            if token_scopes == ():
                # D9 back-compat, and INC-04's fix for existing rows.
                # APIToken.scopes is `mapped_column(JSONB, default=list)`, so every
                # token created through the UI before scopes were settable stored
                # [] — not NULL. Treating that as "no scopes granted" is what makes
                # those tokens 403 on every require_scope route today. None means
                # "unscoped: fall through to the creating user's own permissions",
                # which is what they have always effectively had.
                #
                # Deliberately NOT done inside _normalise_token_scopes: the
                # `uid == 0` service-account branch above calls it too, and a
                # service account has no real creator — inheriting there would
                # promote an empty-scoped service account to superuser.
                token_scopes = None
            _session_cache_set(token_hash, uid, token_scopes)
            _set_request_token_scopes(request, token_scopes)
            return uid
        return None

    return None


async def get_optional_user(request: HTTPConnection, db: Session = Depends(get_db)) -> int | None:
    """Return the authenticated user_id, or None if absent/invalid.

    Returns 0 (service-account sentinel) when the LegacyTokenMiddleware
    has flagged the request (CB_LEGACY_AUTH rollback).  Never raises.
    """
    return resolve_optional_user_id_sync(db, request)


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
