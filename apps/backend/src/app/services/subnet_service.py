"""Subnet calculator and IP utilization analysis (pure Python, no new models)."""

from __future__ import annotations

import ipaddress as _ip
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IPAddress, Network

_logger = logging.getLogger(__name__)


def calculate_subnet(cidr: str) -> dict:
    """Return subnet details for a CIDR string."""
    network = _ip.ip_network(cidr, strict=False)
    hosts = list(network.hosts())
    return {
        "network": str(network.network_address),
        "broadcast": str(network.broadcast_address),
        "netmask": str(network.netmask),
        "wildcard": str(network.hostmask),
        "prefix_length": network.prefixlen,
        "first_usable": str(hosts[0]) if hosts else None,
        "last_usable": str(hosts[-1]) if hosts else None,
        "total_hosts": len(hosts),
        "cidr": str(network),
    }


def get_ip_utilization(db: Session, network_id: int) -> dict:
    """Return IP utilization breakdown for a network."""
    net = db.get(Network, network_id)
    if not net or not net.cidr:
        raise ValueError("Network not found or has no CIDR")

    network = _ip.ip_network(net.cidr, strict=False)
    total_hosts = max(network.num_addresses - 2, 0)  # exclude network + broadcast

    # Count by status
    rows = db.execute(
        select(IPAddress.status, func.count())
        .where(IPAddress.network_id == network_id)
        .group_by(IPAddress.status)
    ).all()
    counts = {row[0]: row[1] for row in rows}

    allocated = counts.get("allocated", 0)
    reserved = counts.get("reserved", 0)
    dhcp = counts.get("dhcp", 0)
    free = counts.get("free", 0)
    tracked = allocated + reserved + dhcp + free

    return {
        "network_id": network_id,
        "cidr": net.cidr,
        "total_hosts": total_hosts,
        "allocated": allocated,
        "reserved": reserved,
        "dhcp": dhcp,
        "free_tracked": free,
        "untracked": max(total_hosts - tracked, 0),
        "utilization_pct": round(allocated / total_hosts * 100, 1) if total_hosts > 0 else 0,
    }


def get_ip_heatmap(db: Session, network_id: int) -> list[dict]:
    """Return a grid of IPs with status for visualization.

    For networks /24 and smaller: each entry = 1 IP.
    For larger networks: aggregate by /24 blocks.
    """
    net = db.get(Network, network_id)
    if not net or not net.cidr:
        raise ValueError("Network not found or has no CIDR")

    network = _ip.ip_network(net.cidr, strict=False)

    # Get all tracked IPs for this network
    ip_rows = (
        db.execute(select(IPAddress).where(IPAddress.network_id == network_id)).scalars().all()
    )
    ip_map = {str(row.address): row for row in ip_rows}

    if network.prefixlen >= 24:
        # Individual IPs
        result = []
        for host in network.hosts():
            addr = str(host)
            row = ip_map.get(addr)
            entry = {
                "ip": addr,
                "status": row.status if row else "untracked",
                "hardware_id": row.hardware_id if row else None,
                "hostname": row.hostname if row else None,
            }
            result.append(entry)
        return result
    else:
        # Aggregate by /24 blocks
        blocks = {}
        for subnet in network.subnets(new_prefix=24):
            block_key = str(subnet)
            total = max(subnet.num_addresses - 2, 0)
            allocated = 0
            free = 0
            reserved = 0
            dhcp_count = 0
            for host in subnet.hosts():
                row = ip_map.get(str(host))
                if row:
                    if row.status == "allocated":
                        allocated += 1
                    elif row.status == "free":
                        free += 1
                    elif row.status == "reserved":
                        reserved += 1
                    elif row.status == "dhcp":
                        dhcp_count += 1
            blocks[block_key] = {
                "block": block_key,
                "total": total,
                "allocated": allocated,
                "free": free,
                "reserved": reserved,
                "dhcp": dhcp_count,
                "untracked": total - allocated - free - reserved - dhcp_count,
            }
        return list(blocks.values())


def suggest_split(cidr: str, new_prefix: int) -> list[str]:
    """Preview splitting a CIDR into smaller subnets."""
    network = _ip.ip_network(cidr, strict=False)
    if new_prefix <= network.prefixlen:
        raise ValueError("New prefix must be longer than current prefix")
    if new_prefix > 30:
        raise ValueError("Cannot split smaller than /30")
    return [str(s) for s in network.subnets(new_prefix=new_prefix)]


def suggest_merge(cidrs: list[str]) -> str | None:
    """Check if CIDRs can be merged into a supernet. Returns merged CIDR or None."""
    if len(cidrs) < 2:
        return None
    networks = [_ip.ip_network(c, strict=False) for c in cidrs]
    try:
        merged = list(_ip.collapse_addresses(networks))
        if len(merged) == 1:
            return str(merged[0])
    except (TypeError, ValueError):
        pass
    return None
