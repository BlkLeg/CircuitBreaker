"""DHCP pool and lease management."""

from __future__ import annotations

import ipaddress as _ip
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import DHCPLease, DHCPPool, IPAddress, Network

_logger = logging.getLogger(__name__)


def create_pool(
    db: Session,
    name: str,
    network_id: int,
    start_ip: str,
    end_ip: str,
    lease_duration_seconds: int = 86400,
    tenant_id: int | None = None,
) -> DHCPPool:
    """Create a DHCP pool, validating range is within network CIDR and non-overlapping."""
    net = db.get(Network, network_id)
    if not net or not net.cidr:
        raise ValueError("Network not found or has no CIDR")

    network = _ip.ip_network(net.cidr, strict=False)
    start = _ip.ip_address(start_ip)
    end = _ip.ip_address(end_ip)

    if start >= end:
        raise ValueError("start_ip must be less than end_ip")
    if start not in network or end not in network:
        raise ValueError("Pool range must be within network CIDR")

    # Check overlap with existing pools in same network
    existing = db.execute(select(DHCPPool).where(DHCPPool.network_id == network_id)).scalars().all()
    for pool in existing:
        ex_start = _ip.ip_address(str(pool.start_ip))
        ex_end = _ip.ip_address(str(pool.end_ip))
        if start <= ex_end and end >= ex_start:
            raise ValueError(f"Overlaps with existing pool '{pool.name}'")

    pool = DHCPPool(
        name=name,
        network_id=network_id,
        start_ip=start_ip,
        end_ip=end_ip,
        lease_duration_seconds=lease_duration_seconds,
        tenant_id=tenant_id,
    )
    db.add(pool)
    db.flush()
    return pool


def import_leases(
    db: Session,
    pool_id: int,
    leases: list[dict],
    tenant_id: int | None = None,
) -> int:
    """Bulk upsert leases by MAC+IP. Returns count of created/updated."""
    count = 0
    for entry in leases:
        ip = entry.get("ip_address")
        mac = entry.get("mac_address")
        hostname = entry.get("hostname")
        if not ip:
            continue

        existing = db.execute(
            select(DHCPLease).where(
                DHCPLease.pool_id == pool_id,
                DHCPLease.ip_address == ip,
            )
        ).scalar_one_or_none()

        if existing:
            if mac:
                existing.mac_address = mac
            if hostname:
                existing.hostname = hostname
            existing.status = "active"
            existing.lease_start = utcnow()
            pool = db.get(DHCPPool, pool_id)
            if pool:
                existing.lease_expiry = utcnow() + timedelta(seconds=pool.lease_duration_seconds)
        else:
            pool = db.get(DHCPPool, pool_id)
            lease = DHCPLease(
                pool_id=pool_id,
                ip_address=ip,
                mac_address=mac,
                hostname=hostname,
                lease_start=utcnow(),
                lease_expiry=utcnow() + timedelta(seconds=pool.lease_duration_seconds)
                if pool
                else None,
                status="active",
                source="import",
                tenant_id=tenant_id,
            )
            db.add(lease)
        count += 1
    db.flush()
    return count


def check_lease_expiry(db: Session) -> list[DHCPLease]:
    """Find and mark expired leases. Returns list of newly expired."""
    now = utcnow()
    expired = (
        db.execute(
            select(DHCPLease).where(
                DHCPLease.status == "active",
                DHCPLease.lease_expiry < now,
            )
        )
        .scalars()
        .all()
    )

    for lease in expired:
        lease.status = "expired"
    if expired:
        db.flush()
    return list(expired)


def is_ip_in_dhcp_range(db: Session, ip_str: str) -> bool:
    """Check if an IP falls within any DHCP pool range."""
    ip = _ip.ip_address(ip_str)
    pools = db.execute(select(DHCPPool).where(DHCPPool.enabled.is_(True))).scalars().all()
    for pool in pools:
        start = _ip.ip_address(str(pool.start_ip))
        end = _ip.ip_address(str(pool.end_ip))
        if start <= ip <= end:
            return True
    return False


def get_pool_utilization(db: Session, pool_id: int) -> dict:
    """Return utilization stats for a DHCP pool."""
    pool = db.get(DHCPPool, pool_id)
    if not pool:
        raise ValueError("Pool not found")

    start = int(_ip.ip_address(str(pool.start_ip)))
    end = int(_ip.ip_address(str(pool.end_ip)))
    total = end - start + 1

    from sqlalchemy import func

    active = (
        db.scalar(
            select(func.count()).where(
                DHCPLease.pool_id == pool_id,
                DHCPLease.status == "active",
            )
        )
        or 0
    )
    expired = (
        db.scalar(
            select(func.count()).where(
                DHCPLease.pool_id == pool_id,
                DHCPLease.status == "expired",
            )
        )
        or 0
    )

    return {
        "total_ips": total,
        "active_leases": active,
        "expired_leases": expired,
        "free": total - active,
        "utilization_pct": round(active / total * 100, 1) if total > 0 else 0,
    }


def tag_discovery_dhcp(db: Session, ip_str: str) -> bool:
    """If IP is in a DHCP range, tag its IPAddress record as 'dhcp'. Returns True if tagged."""
    if not is_ip_in_dhcp_range(db, ip_str):
        return False
    row = db.execute(select(IPAddress).where(IPAddress.address == ip_str)).scalar_one_or_none()
    if row:
        row.status = "dhcp"
        db.flush()
        return True
    return False
