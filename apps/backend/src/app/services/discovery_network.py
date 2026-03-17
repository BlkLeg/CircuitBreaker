"""Network/IP/MAC utilities and constants for discovery."""

import logging
import re

from sqlalchemy.orm import Session

from app.db.models import Network
from app.services.credential_vault import get_vault

logger = logging.getLogger(__name__)


def resolve_vlans_to_cidrs(db: Session, vlan_ids: list[int]) -> tuple[list[str], list[int]]:
    """
    Given a list of VLAN IDs, return (cidrs, network_ids).
    Each VLAN may have multiple networks; de‑duplicate CIDRs.
    """
    if not vlan_ids:
        return [], []
    nets = db.query(Network).filter(Network.vlan_id.in_(vlan_ids)).all()
    cidrs = sorted({n.cidr for n in nets if n.cidr})
    network_ids = [n.id for n in nets]
    return cidrs, network_ids


def _match_ip_to_network(db: Session, ip: str) -> tuple[int | None, int | None]:
    """Match an IP address to the most specific network in the DB.
    Returns (network_id, vlan_id). Uses PostgreSQL INET when available for a single query.
    """
    import ipaddress

    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None, None

    # PostgreSQL: single query with inet >> containment, longest prefix first
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        try:
            row = db.execute(
                text(
                    """
                    SELECT id, vlan_id FROM networks
                    WHERE cidr IS NOT NULL AND cidr != ''
                      AND inet(:ip) << inet(cidr)
                    ORDER BY masklen(inet(cidr)) DESC
                    LIMIT 1
                    """
                ),
                {"ip": ip},
            ).fetchone()
            if row:
                return int(row[0]), int(row[1]) if row[1] is not None else None
            return None, None
        except Exception as e:
            logger.debug(
                "Discovery: IP-to-network query failed, falling back to Python loop: %s",
                e,
                exc_info=True,
            )

    # Fallback: fetch all networks and match in Python (e.g. non-PostgreSQL or query error)
    from sqlalchemy import select as _select

    nets = db.scalars(_select(Network).where(Network.cidr != None)).all()  # noqa: E711
    best_match = None
    max_prefixlen = -1
    ip_obj = ipaddress.ip_address(ip)
    for net in nets:
        if net.cidr is None:
            continue
        try:
            net_obj = ipaddress.ip_network(net.cidr, strict=False)
            if ip_obj in net_obj and net_obj.prefixlen > max_prefixlen:
                max_prefixlen = net_obj.prefixlen
                best_match = net
        except ValueError:
            continue
    if best_match:
        return best_match.id, best_match.vlan_id
    return None, None


def _norm_mac(mac: str | None) -> str | None:
    """Normalize MAC to uppercase colon-separated format."""
    if not mac:
        return None
    cleaned = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(cleaned) != 12:
        return mac.strip().upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2)).upper()


PORT_SERVICE_MAP = {
    80: {"name": "HTTP", "type": "web_server"},
    443: {"name": "HTTPS", "type": "web_server"},
    8006: {"name": "Proxmox", "type": "hypervisor"},
    8060: {"name": "TrueNAS", "type": "storage_appliance"},
    22: {"name": "SSH", "type": "remote_access"},
    3389: {"name": "RDP", "type": "remote_access"},
    161: {"name": "SNMP", "type": "monitoring"},
    8443: {"name": "UniFi", "type": "controller"},
    623: {"name": "IPMI", "type": "out_of_band"},
}

_MAX_CIDR_PREFIXLEN = 12  # Allow at most /12 (e.g. 1M addresses for IPv4)
_MAX_CIDR_ADDRESSES = 1_048_576  # 1M addresses max per CIDR

_NMAP_OVERRIDE_PREFIX = "__nmap_override__:"


def _validate_cidr(cidr: str) -> str:
    """Validate and normalise a CIDR string.
    Raises ValueError with a clear message on any invalid input, /0, or too-large range.
    Never passes unvalidated strings to nmap or any subprocess.
    Returns the normalised CIDR string on success.
    The sentinel value 'docker' is allowed for docker-socket-only scans.
    """
    if cidr == "docker":
        return "docker"
    import ipaddress

    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net.prefixlen == 0:
            raise ValueError("Prefix length /0 is not allowed")
        if net.num_addresses > _MAX_CIDR_ADDRESSES:
            raise ValueError(
                f"CIDR too large (max {_MAX_CIDR_ADDRESSES} addresses). Use a smaller range (e.g. /24)."
            )
        if net.version == 4 and net.prefixlen < _MAX_CIDR_PREFIXLEN:
            raise ValueError(f"IPv4 CIDR must be /{_MAX_CIDR_PREFIXLEN} or smaller (e.g. /24).")
        return str(net)
    except ValueError as exc:
        if (
            "not a valid" in str(exc)
            or "Prefix" in str(exc)
            or "CIDR" in str(exc)
            or "addresses" in str(exc)
        ):
            raise
        raise ValueError(f"'{cidr}' is not a valid CIDR range. Example: '192.168.1.0/24'") from exc


def _decrypt_community(encrypted: str | None) -> str:
    if not encrypted:
        return ""
    vault = get_vault()
    return vault.decrypt(encrypted) or ""
