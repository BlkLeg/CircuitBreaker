"""Network ACL utilities for scan target validation.

Provides CIDR-level checks used by the discovery pipeline to enforce:
 - Air-gap mode (``CB_AIRGAP`` env / ``AppSettings.airgap_mode``)
 - Allowed-network ACL (``AppSettings.scan_allowed_networks``)
 - RFC 1918 private-address enforcement
"""

from __future__ import annotations

import ipaddress
import json
import logging

from fastapi import HTTPException

_logger = logging.getLogger(__name__)

_RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)

_LINK_LOCAL = ipaddress.IPv4Network("169.254.0.0/16")


def is_rfc1918(cidr: str) -> bool:
    """Return True if *every* address in *cidr* is within RFC 1918 private space."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    if net.version != 4:
        return False
    return any(
        net.network_address in rfc and net.broadcast_address in rfc for rfc in _RFC1918_NETWORKS
    )


def is_cidr_allowed(cidr: str, allowed_networks: list[str]) -> bool:
    """Return True if *cidr* is a subnet of at least one allowed network."""
    try:
        target = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    for allowed in allowed_networks:
        try:
            parent = ipaddress.ip_network(allowed, strict=False)
            if isinstance(target, ipaddress.IPv4Network) and isinstance(
                parent, ipaddress.IPv4Network
            ):
                if target.subnet_of(parent):
                    return True
            elif isinstance(target, ipaddress.IPv6Network) and isinstance(
                parent, ipaddress.IPv6Network
            ):
                if target.subnet_of(parent):
                    return True
        except (ValueError, TypeError):
            continue
    return False


def is_ip_in_cidrs(ip_str: str, cidrs_json: str) -> bool:
    """Return True if *ip_str* falls within any CIDR in the JSON array.

    An empty list (``"[]"``) means "allow all".
    """
    try:
        cidrs = json.loads(cidrs_json) if cidrs_json else []
    except (json.JSONDecodeError, TypeError):
        cidrs = []
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(c, strict=False) for c in cidrs)


def parse_allowed_networks(raw: str | None) -> list[str]:
    """Parse a JSON-encoded list of CIDR strings, returning an empty list on error."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return list(parsed) if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def validate_scan_target(
    cidr: str, *, airgap_env: bool, airgap_db: bool, allowed_networks_json: str
) -> None:
    """Unified gate for scan target validation.

    Raises :class:`HTTPException` (403) if the scan should be blocked.
    Called from discovery_service before any nmap/SNMP/ARP work begins.
    """
    if cidr == "docker":
        return

    if airgap_env or airgap_db:
        raise HTTPException(
            status_code=403,
            detail="Scanning is disabled (air-gap mode is active). "
            "Disable CB_AIRGAP or airgap_mode in settings to allow scans.",
        )

    allowed = parse_allowed_networks(allowed_networks_json)
    if allowed and not is_cidr_allowed(cidr, allowed):
        raise HTTPException(
            status_code=403,
            detail=f"Target '{cidr}' is not within the allowed scan networks. Allowed: {allowed}",
        )

    if not is_rfc1918(cidr):
        raise HTTPException(
            status_code=403,
            detail=f"Target '{cidr}' contains public (non-RFC1918) addresses. "
            "Scanning external networks is blocked for security.",
        )
