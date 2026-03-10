"""Rate-limiter singleton with configurable profiles.

Profiles (relaxed / normal / strict) are stored in AppSettings.rate_limit_profile
and determine the per-category rate strings used by @limiter.limit decorators.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

_logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

PROFILES: dict[str, dict[str, str]] = {
    "relaxed": {
        "auth": "20/minute",
        "scan": "5/minute",
        "default": "60/minute",
    },
    "normal": {
        "auth": "5/minute",
        "scan": "1/minute",
        "default": "30/minute",
    },
    "strict": {
        "auth": "3/minute",
        "scan": "1/5minutes",
        "default": "10/minute",
    },
}


def _get_current_profile() -> str:
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


def get_limit(category: str = "default") -> str:
    """Return the rate-limit string for the given category and active profile."""
    profile = _get_current_profile()
    return PROFILES.get(profile, PROFILES["normal"]).get(category, "30/minute")
