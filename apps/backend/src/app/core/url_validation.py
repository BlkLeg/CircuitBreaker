"""Outbound URL validation for SSRF prevention.

All server-side outbound HTTP clients should pass through this module before
they connect.  The policy validates schemes, normalizes hostnames, resolves all
DNS answers, and rejects any disallowed address in a mixed answer set.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.core.config import settings

_LAN_PRIVATE_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv6Network("fc00::/7"),
)


@dataclass(frozen=True)
class OutboundPolicy:
    name: str
    allowed_schemes: frozenset[str]
    allow_private: bool = False
    allow_local: bool = False
    allow_unresolved_hostname: bool = False


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


WEBHOOK_POLICY = OutboundPolicy(
    name="Webhook URL",
    allowed_schemes=frozenset({"http", "https"}),
)
THREAT_FEED_POLICY = OutboundPolicy(
    name="Feed URL",
    allowed_schemes=frozenset({"https"}),
)
LAN_INTEGRATION_POLICY = OutboundPolicy(
    name="Integration URL",
    allowed_schemes=frozenset({"http", "https"}),
    allow_private=True,
    allow_unresolved_hostname=True,
)
MONITOR_TARGET_POLICY = OutboundPolicy(
    name="Monitor URL",
    allowed_schemes=frozenset({"http", "https"}),
    # Watching your own LAN — and the host Circuit Breaker runs on — is the
    # product's whole point, so private and loopback targets stay allowed. What
    # this policy still refuses is what no monitor legitimately needs and what an
    # SSRF wants: link-local, and with it the 169.254.169.254 metadata service,
    # which `_is_forbidden_address` rejects for every policy.
    allow_private=True,
    allow_local=True,
    allow_unresolved_hostname=True,
)
OIDC_POLICY = OutboundPolicy(
    name="OIDC URL",
    allowed_schemes=frozenset({"http", "https"}),
    # On-prem identity providers are normal, so RFC1918/ULA stays allowed; what
    # an attacker-supplied provider config must never reach is loopback or
    # link-local (and with it the cloud metadata service). Hostnames must
    # resolve: an unresolvable IdP is a misconfiguration, not a target.
    allow_private=True,
)
EGRESS_PROXY_POLICY = OutboundPolicy(
    name="Egress proxy URL",
    allowed_schemes=frozenset({"http", "https"}),
    allow_private=True,
    allow_local=True,
    allow_unresolved_hostname=True,
)


def _default_port(scheme: str) -> int:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    raise ValueError(f"URL scheme '{scheme}' is not allowed")


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _is_forbidden_address(ip_str: str, policy: OutboundPolicy) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        return True
    if ip.is_loopback:
        return not policy.allow_local
    if ip.is_private:
        lan_private = any(
            ip.version == network.version and ip in network for network in _LAN_PRIVATE_NETWORKS
        )
        return not (policy.allow_private and lan_private)
    return not ip.is_global


def _validate_host(parsed: object) -> str:
    # Accessing .port can raise ValueError for invalid ports; surface a generic
    # validation failure instead of leaking parser internals to API clients.
    try:
        _ = parsed.port  # type: ignore[attr-defined]
    except ValueError as exc:
        raise ValueError("URL has an invalid port") from exc

    if getattr(parsed, "username", None) or getattr(parsed, "password", None):
        raise ValueError("URL must not include userinfo")

    host = unquote((getattr(parsed, "hostname", None) or "").strip())
    if not host:
        raise ValueError("URL has no host")
    return host


def _resolve_host(host: str, port: int, policy: OutboundPolicy) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        return (str(literal),)

    try:
        infos = socket.getaddrinfo(
            host,
            port,
            family=0,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (socket.gaierror, OSError) as exc:
        if policy.allow_unresolved_hostname:
            return ()
        raise ValueError(f"Cannot resolve URL host: {exc}") from exc

    addresses = _dedupe(str(sockaddr[0]) for *_prefix, sockaddr in infos if sockaddr)
    if not addresses and not policy.allow_unresolved_hostname:
        raise ValueError("URL host did not resolve to any address")
    return addresses


def validate_outbound_url(url: str, policy: OutboundPolicy = WEBHOOK_POLICY) -> ValidatedURL:
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in policy.allowed_schemes:
        allowed = ", ".join(sorted(policy.allowed_schemes))
        raise ValueError(f"{policy.name} scheme '{scheme}' is not allowed; expected {allowed}")

    host = _validate_host(parsed)
    port = parsed.port or _default_port(scheme)
    addresses = _resolve_host(host, port, policy)

    for address in addresses:
        if _is_forbidden_address(address, policy):
            raise ValueError(f"{policy.name} must not target private, reserved, or local networks")

    return ValidatedURL(
        url=parsed.geturl(),
        scheme=scheme,
        host=host,
        port=port,
        addresses=addresses,
    )


def validate_redirect_target(
    source_url: str,
    location: str,
    policy: OutboundPolicy = WEBHOOK_POLICY,
) -> ValidatedURL:
    if not location:
        raise ValueError("Redirect response is missing Location")
    return validate_outbound_url(urljoin(source_url, location), policy)


async def safe_async_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    policy: OutboundPolicy = WEBHOOK_POLICY,
    max_redirects: int = 0,
    **kwargs: Any,
) -> httpx.Response:
    """Validate each outbound request and redirect hop before sending it."""

    current_url = url
    kwargs.pop("follow_redirects", None)
    for _ in range(max_redirects + 1):
        validated = validate_outbound_url(current_url, policy)
        response = await client.request(
            method,
            validated.url,
            follow_redirects=False,
            **kwargs,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        if max_redirects <= 0:
            return response
        location = response.headers.get("location", "")
        current_url = validate_redirect_target(validated.url, location, policy).url
        max_redirects -= 1
        if response.status_code == 303:
            method = "GET"
            kwargs.pop("json", None)
            kwargs.pop("data", None)
            kwargs.pop("content", None)
    raise ValueError("Too many redirects")


def configured_egress_proxy_url() -> str | None:
    proxy_url = settings.egress_proxy_url.strip()
    if not proxy_url:
        return None
    return validate_outbound_url(proxy_url, EGRESS_PROXY_POLICY).url


def outbound_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Create an AsyncClient routed through the configured egress proxy."""

    proxy_url = configured_egress_proxy_url()
    if proxy_url:
        kwargs["proxy"] = proxy_url
        kwargs["trust_env"] = False
    return httpx.AsyncClient(**kwargs)


def validate_lan_target(url: str, label: str) -> None:
    """Re-check a LAN integration target immediately before connecting.

    Integrations validate their URL when an operator saves it, but a hostname
    that pointed at a LAN device then can point at loopback, link-local, or the
    cloud metadata address by the time a poll runs. Calling this from the client
    constructor closes that rebinding window; it raises ``ConnectionError`` so
    it surfaces as an unreachable device rather than an unhandled crash inside a
    poller.
    """
    try:
        validate_outbound_url(url, LAN_INTEGRATION_POLICY)
    except ValueError as exc:
        raise ConnectionError(f"{label} rejected: {exc}") from exc


def reject_ssrf_url(url: str) -> None:
    """Raise ValueError if a generic webhook/public URL is SSRF unsafe."""

    validate_outbound_url(url, WEBHOOK_POLICY)


def reject_ssrf_url_proxmox(url: str) -> None:
    """Raise ValueError if a LAN integration URL targets local-only addresses."""

    try:
        validate_outbound_url(url, LAN_INTEGRATION_POLICY)
    except ValueError as exc:
        msg = str(exc)
        if "private, reserved, or local networks" in msg:
            raise ValueError("Proxmox URL must not target loopback or link-local IPs") from exc
        raise
