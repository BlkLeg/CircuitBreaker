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


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _default_port(scheme: str) -> int:
    try:
        return _DEFAULT_PORTS[scheme]
    except KeyError:
        raise ValueError(f"URL scheme '{scheme}' is not allowed") from None


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


def _bracketed(host: str) -> str:
    """Wrap an IPv6 literal in brackets so it is legal in a netloc or Host header."""

    return f"[{host}]" if ":" in host else host


def _ascii_host(host: str) -> str:
    """Punycode a hostname so it is legal in a ``Host`` header.

    httpx IDNA-encodes ``URL.host`` on its way to the wire, so before the pin an
    IDN webhook sent ``Host: xn--bcher-kva.example``.  The pin builds the header
    itself out of ``validated.host``, which is raw Unicode from
    ``urlparse().hostname``; handing that to httpx puts UTF-8 bytes in a header
    field that must be ASCII.  Hosts the stdlib codec refuses (an empty or
    over-long label) are passed through unchanged -- validation already accepted
    the URL, and a header we cannot spell is not a reason to drop the request.
    """

    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return host


def _reaches_through_proxy(client: httpx.AsyncClient | httpx.Client | None, url: str) -> bool:
    """True when this client will send *url* to a forward proxy instead of dialing it.

    This is load-bearing, not a nicety.  httpcore honours the ``sni_hostname``
    extension on a direct connection, but ``AsyncTunnelHTTPConnection``
    (``httpcore/_async/http_proxy.py``) builds its TLS ``server_hostname`` from
    ``self._remote_origin.host`` -- the host in the request URL -- and never
    looks at ``request.extensions``.  Pin the URL to an IP literal on that path
    and every HTTPS request dies with ``certificate verify failed: IP address
    mismatch``.  That is the deployment ``docs/deployment-security.md`` tells
    operators to run, so an unconditional pin trades a rebinding window for a
    total notification outage on the *hardened* configuration.

    Skipping the pin there costs nothing that was ever there: behind a proxy the
    name is resolved by the proxy, not by this process, so there is no local
    second lookup for a rebinding answer to win.  What guards egress in that
    deployment is the proxy's own policy.

    httpx exposes proxy wiring only privately.  ``_transport_for_url`` returns
    ``client._transport`` when no mount matches, and a *different* transport
    when one does -- a proxy from ``proxy=``, one from ``HTTPS_PROXY`` under
    ``trust_env``, or an explicit ``mounts=`` entry.  Anything that is not
    provably the client's own transport is treated as proxied, and so is a
    client whose internals we cannot read at all: getting this wrong towards
    "proxied" costs the rebinding hardening, getting it wrong the other way
    takes the install off the air.
    """

    if client is None:
        return True
    try:
        return client._transport_for_url(httpx.URL(url)) is not client._transport
    except Exception:  # noqa: BLE001 -- unreadable internals must not break the send
        return True


def pinned_request(
    validated: ValidatedURL,
    kwargs: dict[str, Any],
    client: httpx.AsyncClient | httpx.Client | None,
) -> tuple[str, dict[str, Any]]:
    """Rewrite a validated request so it dials an address that was already approved.

    ``validate_outbound_url`` resolves the hostname and rejects the answer set if
    any address is private, loopback, link-local or otherwise reserved.  Handing
    the *name* back to httpx then throws that work away: the connection pool
    resolves a second time at connect, and a TTL-0 rebinding answer can move the
    socket to 127.0.0.1 or 169.254.169.254 in the gap between the two lookups.
    The check is real, it is just checking a different answer than the one that
    gets dialed.

    Dialing the IP literal removes the second lookup, and with it the window.
    Two things have to travel with it or the pin would break working requests:

    * ``Host`` keeps the original name (punycoded, and with its port when it is
      not the scheme default), so virtual-hosted servers still route to the
      right site.
    * ``sni_hostname`` keeps the original name as the TLS ``server_hostname``
      (httpcore 1.x reads this extension on a direct connection; httpx's default
      SSLContext has ``check_hostname=True``), so the certificate is still
      verified against the real hostname and not against the IP literal.

    ``client`` is required and is not decoration: the pin is skipped whenever
    that client would reach the URL through a forward proxy, because httpcore's
    CONNECT path ignores ``sni_hostname`` -- see ``_reaches_through_proxy``.
    Pass the client the request will actually be sent on; do not pass ``None``
    to make a caller compile, that silently disables the pin.

    Maintainers: do not "simplify" this by passing ``validated.url`` to the
    client again.  The name form is still the right base for ``urljoin`` on a
    redirect Location -- that is why ``safe_async_request`` keeps it for that --
    but on a direct connection it must not be what the socket is opened to.

    Policies with ``allow_unresolved_hostname`` may carry no addresses at all
    (``LAN_INTEGRATION_POLICY``, ``MONITOR_TARGET_POLICY``, ``EGRESS_PROXY_POLICY``
    when DNS is unavailable).  There is nothing to pin then, so the name is kept
    and those requests keep the pre-existing check-then-connect window; closing
    that would mean refusing to talk to hosts this deployment cannot resolve.
    """

    if not validated.addresses or _reaches_through_proxy(client, validated.url):
        # Return the caller's kwargs untouched, headers and extensions included:
        # the proxied path has to behave exactly as it did before the pin
        # existed, or the skip would not be a skip.
        return validated.url, kwargs

    # Every address in the set passed `_is_forbidden_address`, so any of them is
    # safe to dial; the first is the resolver's own preference order.
    parsed = urlparse(validated.url)
    literal = _bracketed(validated.addresses[0])
    host_header = _bracketed(_ascii_host(validated.host))
    if validated.port != _DEFAULT_PORTS.get(validated.scheme):
        host_header = f"{host_header}:{validated.port}"

    kwargs = dict(kwargs)
    headers = httpx.Headers(kwargs.get("headers") or {})
    headers["Host"] = host_header
    kwargs["headers"] = headers
    extensions = dict(kwargs.get("extensions") or {})
    extensions.setdefault("sni_hostname", _ascii_host(validated.host))
    kwargs["extensions"] = extensions
    return parsed._replace(netloc=f"{literal}:{validated.port}").geturl(), kwargs


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
        target, send_kwargs = pinned_request(validated, kwargs, client)
        response = await client.request(
            method,
            target,
            follow_redirects=False,
            **send_kwargs,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        if max_redirects <= 0:
            return response
        location = response.headers.get("location", "")
        # The redirect base stays the *name* form on purpose: a relative Location
        # has to resolve against the real host, not against the pinned literal.
        # The next iteration re-validates and re-pins, so the hop is dialed by
        # address too.
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
