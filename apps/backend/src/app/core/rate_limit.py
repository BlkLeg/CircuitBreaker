"""Rate-limiter singleton with configurable profiles.

Profiles (relaxed / normal / strict) are stored in AppSettings.rate_limit_profile
and determine the per-category rate strings used by @limiter.limit decorators.
"""

import logging
import threading
import time

from slowapi import Limiter
from slowapi.util import get_remote_address

_logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)

_PROFILE_CACHE_TTL_S = 300
_profile_cache: tuple[str, float] | None = None
_profile_cache_lock = threading.Lock()

PROFILES: dict[str, dict[str, str]] = {
    "relaxed": {
        "auth": "20/minute",
        "ip_check": "30/minute",
        "mfa_verify": "10/15minutes",
        "scan": "5/minute",
        "telemetry": "30/minute",
        "default": "60/minute",
    },
    "normal": {
        "auth": "5/minute",
        "ip_check": "10/minute",
        "mfa_verify": "5/15minutes",
        "scan": "1/minute",
        "telemetry": "15/minute",
        "default": "30/minute",
    },
    "strict": {
        "auth": "3/minute",
        "ip_check": "5/minute",
        "mfa_verify": "3/15minutes",
        "scan": "1/5minutes",
        "telemetry": "5/minute",
        "default": "10/minute",
    },
}


def _fetch_profile_from_db() -> str:
    """Read rate_limit_profile from AppSettings. Falls back to 'normal'."""
    try:
        from app.db.session import SessionLocal
        from app.services.settings_service import get_or_create_settings

        db = SessionLocal()
        try:
            cfg = get_or_create_settings(db)
            return getattr(cfg, "rate_limit_profile", "normal") or "normal"
        finally:
            db.close()
    except Exception:
        return "normal"


def _get_current_profile() -> str:
    """Return the active rate-limit profile, using in-memory cache with TTL."""
    global _profile_cache
    now = time.monotonic()
    with _profile_cache_lock:
        if _profile_cache is not None and (now - _profile_cache[1]) < _PROFILE_CACHE_TTL_S:
            return _profile_cache[0]
    profile = _fetch_profile_from_db()
    with _profile_cache_lock:
        _profile_cache = (profile, time.monotonic())
    return profile


def invalidate_rate_limit_profile_cache() -> None:
    """Clear the cached rate-limit profile so the next get_limit() refetches from DB."""
    global _profile_cache
    with _profile_cache_lock:
        _profile_cache = None


def get_limit(category: str = "default") -> str:
    """Return the rate-limit string for the given category and active profile."""
    profile = _get_current_profile()
    return PROFILES.get(profile, PROFILES["normal"]).get(category, "30/minute")
