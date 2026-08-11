"""Rate-limiter singleton with configurable profiles.

Profiles (relaxed / normal / strict) are stored in AppSettings.rate_limit_profile
and determine the per-category rate strings used by @limiter.limit decorators.
"""

import ipaddress
import logging
import threading
import time
from urllib.parse import quote, urlparse, urlunparse

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.redis import _resolve_redis_password

_logger = logging.getLogger(__name__)
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_PROFILE_CACHE_TTL_S = 300
_profile_cache: tuple[str, float] | None = None
_profile_cache_lock = threading.Lock()
_trusted_proxy_cache: tuple[tuple[_IPNetwork, ...], tuple[str, ...]] | None = None

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


def _rate_limit_storage_uri() -> str:
    explicit = settings.rate_limit_storage_url.strip()
    if explicit:
        return explicit

    redis_url = settings.redis_url.strip()
    password = _resolve_redis_password(redis_url)
    if not password:
        return redis_url

    parsed = urlparse(redis_url)
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    auth = f"{quote(username, safe='')}:" if username else ":"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{auth}{quote(password, safe='')}@{hostname}{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, ""))


def _trusted_proxy_networks() -> tuple[_IPNetwork, ...]:
    global _trusted_proxy_cache
    raw = tuple(settings.trusted_proxy_cidrs)
    if _trusted_proxy_cache and _trusted_proxy_cache[1] == raw:
        return _trusted_proxy_cache[0]

    networks: list[_IPNetwork] = []
    for cidr in raw:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            _logger.warning("Ignoring invalid trusted proxy CIDR: %s", cidr)
    _trusted_proxy_cache = (tuple(networks), raw)
    return _trusted_proxy_cache[0]


def _client_host(request: object) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "")


def _request_from_trusted_proxy(request: object) -> bool:
    host = _client_host(request)
    if not host:
        return False
    try:
        peer = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(peer.version == net.version and peer in net for net in _trusted_proxy_networks())


def _first_forwarded_for(headers: object) -> str:
    raw = ""
    if hasattr(headers, "get"):
        raw = str(headers.get("x-forwarded-for") or "")
    return raw.split(",", 1)[0].strip()


def trusted_client_identity(request: object) -> str:
    """Return the rate-limit key, honoring forwarded identity only from trusted proxies."""

    if _request_from_trusted_proxy(request):
        forwarded = _first_forwarded_for(getattr(request, "headers", {}))
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                _logger.debug("Ignoring invalid X-Forwarded-For value from trusted proxy")
    return get_remote_address(request)


limiter = Limiter(
    key_func=trusted_client_identity,
    headers_enabled=True,
    storage_uri=_rate_limit_storage_uri(),
    strategy="fixed-window",
    swallow_errors=False,
)


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
