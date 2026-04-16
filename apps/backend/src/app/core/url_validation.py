"""URL validation for SSRF prevention.

Rejects loopback, link-local, and private IPs.  Also rejects non-HTTP(S)
schemes to prevent ``file://``, ``gopher://``, ``ftp://``, etc.
"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_forbidden_ip(ip_str: str) -> bool:
    """Return True if the IP is loopback, link-local, or private (RFC1918)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return ip.is_loopback or ip.is_link_local or ip.is_private


def _is_forbidden_ip_for_webhook(ip_str: str) -> bool:
    """Same as _is_forbidden_ip: loopback, link-local, private."""
    return _is_forbidden_ip(ip_str)


def _is_forbidden_ip_proxmox(ip_str: str) -> bool:
    """For Proxmox: forbid only loopback and link-local (allow private/LAN)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return ip.is_loopback or ip.is_link_local


def reject_ssrf_url(url: str) -> None:
    """Raise ValueError if the URL host resolves to a forbidden IP (SSRF).

    Forbidden: loopback (127.0.0.0/8, ::1), link-local (169.254.0.0/16, fe80::/10),
    private (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).
    """
    _reject_ssrf_impl(
        url,
        _is_forbidden_ip_for_webhook,
        "Webhook URL must not target loopback, link-local, or private IPs",
        allow_unresolved_hostname=False,
    )


def reject_ssrf_url_proxmox(url: str) -> None:
    """Raise ValueError if the URL host is loopback or link-local.

    Allows private (RFC1918) for LAN Proxmox.
    """
    _reject_ssrf_impl(
        url,
        _is_forbidden_ip_proxmox,
        "Proxmox URL must not target loopback or link-local IPs",
        allow_unresolved_hostname=True,
    )


def _reject_ssrf_impl(
    url: str,
    is_forbidden: Callable[[str], bool],
    msg: str,
    *,
    allow_unresolved_hostname: bool = False,
) -> None:
    parsed = urlparse(url)

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"URL scheme '{scheme}' is not allowed. Only HTTP and HTTPS are permitted."
        )

    host = (parsed.hostname or parsed.netloc or "").strip()
    if not host:
        raise ValueError("URL has no host")
    # If host is a literal IP, check it directly
    try:
        ipaddress.ip_address(host)
        if is_forbidden(host):
            raise ValueError(msg)
        return
    except ValueError as ve:
        if "must not" in str(ve):
            raise
    # Host is a hostname; resolve and check each IP
    try:
        infos = socket.getaddrinfo(host, None, family=0, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as e:
        if allow_unresolved_hostname:
            return
        raise ValueError(f"Cannot resolve URL host: {e}") from e
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = str(sockaddr[0]) if sockaddr else None
        if ip_str and is_forbidden(ip_str):
            raise ValueError(msg)
