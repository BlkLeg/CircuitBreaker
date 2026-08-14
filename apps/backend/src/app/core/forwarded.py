"""One answer to "what did the peer actually tell us, and may we believe it?".

`X-Forwarded-*` headers are client-supplied strings. They are only evidence
when the socket peer is a reverse proxy we run, because anything else can set
them freely. SEC-13 established that model for `X-Forwarded-For` and the rate
limiter, but the rest of the codebase read `X-Forwarded-Proto` and
`X-Forwarded-Host` straight off the request from any peer — so the same header
was authoritative in one module and forgeable in the next.

Everything that needs a forwarded value goes through here, so the trust
decision is made once. Callers get the safe fallback (the socket peer, the real
URL scheme, the `Host` header) whenever the peer is not trusted.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from app.core.config import settings

_logger = logging.getLogger(__name__)
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_trusted_proxy_cache: tuple[tuple[_IPNetwork, ...], tuple[str, ...]] | None = None


def trusted_proxy_networks() -> tuple[_IPNetwork, ...]:
    """Parsed `trusted_proxy_cidrs`, re-parsed whenever the setting changes."""
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


def _is_trusted(address: str) -> bool:
    if not address:
        return False
    try:
        peer = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(peer.version == net.version and peer in net for net in trusted_proxy_networks())


def client_host(conn: Any) -> str:
    """The socket peer address, as a string ("" when unavailable)."""
    client = getattr(conn, "client", None)
    host = getattr(client, "host", None)
    if host:
        return str(host)
    # WebSocket scope dicts carry the peer as a (host, port) tuple.
    scope = conn if isinstance(conn, dict) else getattr(conn, "scope", None)
    if isinstance(scope, dict):
        pair = scope.get("client")
        if isinstance(pair, (list, tuple)) and pair:
            return str(pair[0])
    return ""


def request_from_trusted_proxy(conn: Any) -> bool:
    """Whether this connection's peer is one of our own reverse proxies."""
    return _is_trusted(client_host(conn))


def _header(conn: Any, name: str) -> str:
    """Case-insensitive header read that works for Request and WebSocket."""
    headers = getattr(conn, "headers", None)
    if headers is None and isinstance(conn, dict):
        raw = conn.get("headers") or []
        target = name.encode()
        for key, value in raw:
            if key.lower() == target:
                return str(value.decode("latin-1"))
        return ""
    if headers is None:
        return ""
    if hasattr(headers, "get"):
        value = headers.get(name)
        return str(value) if value else ""
    return ""


def forwarded_client_identity(headers: Any) -> str:
    """Return the rightmost `X-Forwarded-For` hop we did not put there ourselves.

    The shipped nginx *appends* (`$proxy_add_x_forwarded_for`), so a client's own
    header survives to the left of its real address. Reading left to right would
    therefore let any caller choose its own rate-limit key and rotate identities
    past the login and MFA limits. Walking right to left and stopping at the
    first hop outside `trusted_proxy_cidrs` yields the nearest address an
    attacker cannot forge: everything further left was written by an untrusted
    party. Returns "" when the whole chain is our own proxies (or unreadable),
    leaving the caller on the socket peer.
    """
    raw = ""
    if hasattr(headers, "get"):
        raw = str(headers.get("x-forwarded-for") or "")
    if not raw:
        return ""

    for entry in reversed(raw.split(",")):
        entry = entry.strip()
        if not entry:
            continue
        try:
            candidate = ipaddress.ip_address(entry)
        except ValueError:
            # An unreadable hop ends the verifiable chain — anything to its left
            # is hearsay, so fall back to the peer rather than guess.
            _logger.debug("Ignoring invalid X-Forwarded-For value from trusted proxy")
            return ""
        if _is_trusted(str(candidate)):
            continue
        return str(candidate)
    return ""


def forwarded_proto(conn: Any, default: str = "") -> str:
    """The request scheme, honouring `X-Forwarded-Proto` only behind a trusted proxy.

    Untrusted peers get `default` (normally the real scheme), so a plain-HTTP
    caller cannot claim `https` and talk the app into marking cookies `Secure`,
    emitting HSTS, or minting `https://` OAuth redirect URIs it will not serve.
    """
    if not request_from_trusted_proxy(conn):
        return default
    value = _header(conn, "x-forwarded-proto")
    if not value:
        return default
    # May be a comma-separated chain; the leftmost entry is the original scheme
    # and every hop in the chain is one of ours, so it is trustworthy here.
    return value.split(",")[0].strip().lower() or default


def forwarded_host(conn: Any, default: str = "") -> str:
    """The external host, honouring `X-Forwarded-Host` only behind a trusted proxy.

    Untrusted peers get `default` (normally the `Host` header). This is what
    keeps an attacker from steering generated absolute URLs — OAuth redirects,
    password-reset links — at a host they control.
    """
    if not request_from_trusted_proxy(conn):
        return default
    value = _header(conn, "x-forwarded-host")
    if not value:
        return default
    return value.split(",")[0].strip() or default
