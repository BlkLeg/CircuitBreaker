"""Bulk suggestion intelligence for the enhanced review queue.

Provides smart grouping, network inference, vendor catalog matching,
rack slot finding, duplicate detection, and service naming suggestions
for multi-select merge operations.
"""

import ipaddress
import json
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Hardware, HardwareNetwork, Network, Rack, ScanResult,
)

logger = logging.getLogger(__name__)

# ── Vendor catalog singleton ────────────────────────────────────────────────

_VENDOR_CATALOG: dict | None = None
_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "vendor_catalog.json"


def get_vendor_catalog() -> dict:
    """Load and cache vendor_catalog.json in-memory."""
    global _VENDOR_CATALOG
    if _VENDOR_CATALOG is None:
        try:
            _VENDOR_CATALOG = json.loads(_CATALOG_PATH.read_text())
        except Exception as e:
            logger.warning(f"Failed to load vendor catalog: {e}")
            _VENDOR_CATALOG = {}
    return _VENDOR_CATALOG


# ── Extended port → service map ─────────────────────────────────────────────

EXTENDED_PORT_SERVICE_MAP = {
    22:    {"name": "SSH",                  "category": "remote_access"},
    80:    {"name": "HTTP",                 "category": "web_server"},
    443:   {"name": "HTTPS",                "category": "web_server"},
    161:   {"name": "SNMP",                 "category": "monitoring"},
    623:   {"name": "IPMI",                 "category": "out_of_band"},
    3000:  {"name": "Grafana",              "category": "monitoring"},
    3389:  {"name": "RDP",                  "category": "remote_access"},
    5000:  {"name": "Docker Registry",      "category": "infrastructure"},
    5900:  {"name": "VNC",                  "category": "remote_access"},
    8006:  {"name": "Proxmox VE",           "category": "hypervisor"},
    8060:  {"name": "TrueNAS",              "category": "storage"},
    8080:  {"name": "HTTP Proxy",           "category": "web_server"},
    8096:  {"name": "Jellyfin",             "category": "media"},
    8123:  {"name": "Home Assistant",       "category": "automation"},
    8443:  {"name": "UniFi Controller",     "category": "controller"},
    8888:  {"name": "Portainer",            "category": "infrastructure"},
    9090:  {"name": "Prometheus",           "category": "monitoring"},
    9100:  {"name": "Node Exporter",        "category": "monitoring"},
    19999: {"name": "Netdata",              "category": "monitoring"},
    32400: {"name": "Plex Media Server",    "category": "media"},
    51820: {"name": "WireGuard",            "category": "vpn"},
}

# ── Port → vendor fingerprint map ──────────────────────────────────────────

_PORT_VENDOR_HINTS: dict[int, str] = {
    8006: "proxmox",
    8060: "truenas",
    8443: "ubiquiti",
    623:  "dell",       # IPMI — best guess Dell iDRAC
}

# ── OS string → vendor hints ───────────────────────────────────────────────

_OS_VENDOR_HINTS: list[tuple[str, str]] = [
    ("proxmox",     "proxmox"),
    ("pve",         "proxmox"),
    ("truenas",     "truenas"),
    ("freenas",     "truenas"),
    ("unifi",       "ubiquiti"),
    ("ubnt",        "ubiquiti"),
    ("mikrotik",    "mikrotik"),
    ("routeros",    "mikrotik"),
    ("pfsense",     "pfsense"),
    ("opnsense",    "opnsense"),
    ("synology",    "synology"),
    ("idrac",       "dell"),
    ("ilo",         "hp"),
    ("supermicro",  "supermicro"),
    ("dell",        "dell"),
    ("hewlett",     "hp"),
    ("raspberry",   "raspberry_pi"),
    ("raspbian",    "raspberry_pi"),
    ("apc",         "apc"),
    ("cyberpower",  "cyberpower"),
    ("netgear",     "netgear"),
    ("tp-link",     "tp_link"),
    ("asus",        "asus"),
    ("firewalla",   "firewalla"),
    ("protectli",   "protectli"),
]


def _parse_ports(open_ports_json: str | None) -> list[dict]:
    """Parse open_ports_json string into a list of port dicts."""
    if not open_ports_json:
        return []
    try:
        return json.loads(open_ports_json)
    except (json.JSONDecodeError, TypeError):
        return []


def _get_port_numbers(result: ScanResult) -> set[int]:
    """Extract port numbers from a scan result."""
    ports = _parse_ports(result.open_ports_json)
    return {int(p.get("port", 0)) for p in ports if p.get("port")}


def _infer_vendor_key(result: ScanResult) -> str | None:
    """Infer vendor key from OS, SNMP, and port fingerprints."""
    search_strings = []
    if result.os_vendor:
        search_strings.append(result.os_vendor.lower())
    if result.os_family:
        search_strings.append(result.os_family.lower())
    if result.snmp_sys_descr:
        search_strings.append(result.snmp_sys_descr.lower())
    if result.snmp_sys_name:
        search_strings.append(result.snmp_sys_name.lower())
    if result.hostname:
        search_strings.append(result.hostname.lower())

    combined = " ".join(search_strings)

    # Check OS / SNMP strings first (higher confidence)
    for pattern, vendor_key in _OS_VENDOR_HINTS:
        if pattern in combined:
            return vendor_key

    # Fall back to port-based hints
    port_numbers = _get_port_numbers(result)
    for port, vendor_key in _PORT_VENDOR_HINTS.items():
        if port in port_numbers:
            return vendor_key

    return None


def _pick_best_device(vendor_key: str, result: ScanResult) -> dict | None:
    """Pick the best device from vendor catalog based on scan data.

    Returns dict with {vendor_key, device_key, label, icon, role, u_height, telemetry_profile}.
    """
    catalog = get_vendor_catalog()
    vendor = catalog.get(vendor_key)
    if not vendor or "devices" not in vendor:
        return None

    devices = vendor["devices"]
    if not devices:
        return None

    # If only one device, use it
    if len(devices) == 1:
        device_key = next(iter(devices))
        d = devices[device_key]
        return {
            "vendor_key": vendor_key,
            "device_key": device_key,
            "label": f"{vendor['label']} {d['label']}",
            "icon": vendor.get("icon"),
            "role": d.get("role", "server"),
            "u_height": d.get("u_height"),
            "telemetry_profile": d.get("telemetry_profile"),
        }

    # For multi-device vendors, return vendor-level match
    # (user picks specific device in the UI typeahead)
    first_key = next(iter(devices))
    first = devices[first_key]
    return {
        "vendor_key": vendor_key,
        "device_key": None,
        "label": vendor["label"],
        "icon": vendor.get("icon"),
        "role": first.get("role", "server"),
        "u_height": first.get("u_height"),
        "telemetry_profile": first.get("telemetry_profile"),
    }


# ── Main suggestion function ───────────────────────────────────────────────


def suggest_bulk_actions(db: Session, result_ids: list[int]) -> dict:
    """Compute intelligent suggestions for a set of scan results.

    Returns:
        {
            "clusters": [{"name": str, "result_ids": [int], "vendor": str|None}],
            "networks": [{"name": str, "cidr": str, "existing_id": int|None, "result_ids": [int]}],
            "catalog_matches": {result_id: {vendor_key, device_key, label, icon, role, u_height}},
            "rack_suggestions": [{"rack_id": int, "rack_name": str, "free_slots": [int], "height_u": int}],
            "duplicates": [{"result_id": int, "ip": str, "existing_hardware_id": int, "existing_name": str}],
            "services": {result_id: [{"port": int, "name": str, "category": str}]},
            "role_summary": {"server": [result_id, ...], "hypervisor": [...], ...},
        }
    """
    results = db.execute(
        select(ScanResult).where(ScanResult.id.in_(result_ids))
    ).scalars().all()

    if not results:
        return {
            "clusters": [], "networks": [], "catalog_matches": {},
            "rack_suggestions": [], "duplicates": [], "services": {},
            "role_summary": {},
        }

    catalog_matches = _suggest_catalog_matches(results)
    clusters = _suggest_clusters(results, catalog_matches)
    networks = _suggest_networks(db, results)
    rack_suggestions = _suggest_racks(db, results, catalog_matches)
    duplicates = _detect_duplicates(db, results)
    services = _suggest_services(results)
    role_summary = _summarize_roles(results, catalog_matches)

    return {
        "clusters": clusters,
        "networks": networks,
        "catalog_matches": catalog_matches,
        "rack_suggestions": rack_suggestions,
        "duplicates": duplicates,
        "services": services,
        "role_summary": role_summary,
    }


# ── Cluster grouping ───────────────────────────────────────────────────────


def _suggest_clusters(
    results: list[ScanResult],
    catalog_matches: dict[int, dict],
) -> list[dict]:
    """Group results by shared /24 subnet + vendor into cluster suggestions."""
    groups: dict[str, list[ScanResult]] = {}

    for r in results:
        if not r.ip_address:
            continue
        try:
            ip = ipaddress.ip_address(r.ip_address)
            subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        except ValueError:
            continue

        vendor = None
        match = catalog_matches.get(r.id)
        if match:
            vendor = match.get("vendor_key")

        key = f"{subnet}:{vendor or 'unknown'}"
        groups.setdefault(key, []).append(r)

    clusters = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        subnet_part, vendor_part = key.rsplit(":", 1)
        catalog = get_vendor_catalog()
        vendor_label = catalog.get(vendor_part, {}).get("label", vendor_part.title())
        if vendor_part == "unknown":
            name = f"Cluster ({subnet_part})"
        else:
            name = f"{vendor_label} Cluster"

        clusters.append({
            "name": name,
            "result_ids": [r.id for r in members],
            "vendor": vendor_part if vendor_part != "unknown" else None,
            "subnet": subnet_part,
        })

    return clusters


# ── Network inference ──────────────────────────────────────────────────────


def _suggest_networks(db: Session, results: list[ScanResult]) -> list[dict]:
    """Infer shared subnets and match to existing networks."""
    subnet_groups: dict[str, list[ScanResult]] = {}

    for r in results:
        if not r.ip_address:
            continue
        try:
            ip = ipaddress.ip_address(r.ip_address)
            subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        except ValueError:
            continue
        subnet_groups.setdefault(subnet, []).append(r)

    suggestions = []
    for cidr, members in subnet_groups.items():
        # Check for existing network with this CIDR
        existing = db.execute(
            select(Network).where(Network.cidr == cidr)
        ).scalar_one_or_none()

        # Guess gateway as .1
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            gateway_guess = str(list(net.hosts())[0]) if net.num_addresses > 1 else None
        except (ValueError, IndexError):
            gateway_guess = None

        suggestions.append({
            "name": existing.name if existing else f"Network {cidr}",
            "cidr": cidr,
            "existing_id": existing.id if existing else None,
            "result_ids": [r.id for r in members],
            "gateway_guess": gateway_guess,
        })

    return suggestions


# ── Vendor catalog matching ────────────────────────────────────────────────


def _suggest_catalog_matches(results: list[ScanResult]) -> dict[int, dict]:
    """Fuzzy-match each result to vendor catalog entries."""
    matches = {}
    for r in results:
        vendor_key = _infer_vendor_key(r)
        if vendor_key:
            device = _pick_best_device(vendor_key, r)
            if device:
                matches[r.id] = device
    return matches


# ── Rack suggestions ───────────────────────────────────────────────────────


def _suggest_racks(
    db: Session,
    results: list[ScanResult],
    catalog_matches: dict[int, dict],
) -> list[dict]:
    """Find racks with enough free U-slots for the incoming hardware."""
    count = len(results)
    if count == 0:
        return []

    # Determine average u_height from catalog matches (default 1)
    heights = [
        m.get("u_height", 1)
        for m in catalog_matches.values()
        if m.get("u_height")
    ]
    avg_height = max(1, round(sum(heights) / len(heights))) if heights else 1

    racks = db.execute(select(Rack)).scalars().all()
    suggestions = []

    for rack in racks:
        occupied = set()
        hw_in_rack = db.execute(
            select(Hardware).where(
                Hardware.rack_id == rack.id,
                Hardware.rack_unit.isnot(None),
                Hardware.u_height.isnot(None),
            )
        ).scalars().all()

        for hw in hw_in_rack:
            for u in range(hw.rack_unit, hw.rack_unit + (hw.u_height or 1)):
                occupied.add(u)

        # Find contiguous free ranges
        free_slots = []
        consecutive = 0
        start_u = None
        for u in range(1, rack.height_u + 1):
            if u not in occupied:
                if consecutive == 0:
                    start_u = u
                consecutive += 1
            else:
                if consecutive >= avg_height:
                    free_slots.append(start_u)
                consecutive = 0
                start_u = None
        if consecutive >= avg_height and start_u is not None:
            free_slots.append(start_u)

        total_free = rack.height_u - len(occupied)
        needed = count * avg_height

        if total_free >= needed:
            suggestions.append({
                "rack_id": rack.id,
                "rack_name": rack.name,
                "height_u": rack.height_u,
                "free_u": total_free,
                "free_start_slots": free_slots[:count],
                "avg_device_height": avg_height,
            })

    return suggestions


# ── Duplicate detection ────────────────────────────────────────────────────


def _detect_duplicates(db: Session, results: list[ScanResult]) -> list[dict]:
    """Check if any result IPs or MACs already exist as hardware
    beyond the scanner's own matched_entity linkage."""
    duplicates = []

    for r in results:
        if r.state != "new":
            # matched/conflict already handled by scanner
            continue

        conditions = []
        if r.ip_address:
            conditions.append(Hardware.ip_address == r.ip_address)
        if r.mac_address:
            conditions.append(Hardware.mac_address == r.mac_address)

        if not conditions:
            continue

        from sqlalchemy import or_
        existing = db.execute(
            select(Hardware).where(or_(*conditions))
        ).scalars().first()

        if existing:
            duplicates.append({
                "result_id": r.id,
                "ip": r.ip_address,
                "mac": r.mac_address,
                "existing_hardware_id": existing.id,
                "existing_name": existing.name,
            })

    return duplicates


# ── Service suggestions ────────────────────────────────────────────────────


def _suggest_services(results: list[ScanResult]) -> dict[int, list[dict]]:
    """Map open ports to named service suggestions."""
    result_services = {}

    for r in results:
        ports = _parse_ports(r.open_ports_json)
        if not ports:
            continue

        suggestions = []
        for p in ports:
            port_num = int(p.get("port", 0))
            if port_num in EXTENDED_PORT_SERVICE_MAP:
                svc = EXTENDED_PORT_SERVICE_MAP[port_num]
                suggestions.append({
                    "port": port_num,
                    "protocol": p.get("protocol", "tcp"),
                    "name": svc["name"],
                    "category": svc["category"],
                    "nmap_name": p.get("name", ""),
                    "nmap_version": p.get("version", ""),
                })
            else:
                # Include unmapped ports with nmap-detected name
                suggestions.append({
                    "port": port_num,
                    "protocol": p.get("protocol", "tcp"),
                    "name": p.get("name", f"Port {port_num}"),
                    "category": "misc",
                    "nmap_name": p.get("name", ""),
                    "nmap_version": p.get("version", ""),
                })

        if suggestions:
            result_services[r.id] = suggestions

    return result_services


# ── Role summary ───────────────────────────────────────────────────────────


def _summarize_roles(
    results: list[ScanResult],
    catalog_matches: dict[int, dict],
) -> dict[str, list[int]]:
    """Summarize suggested roles across results."""
    roles: dict[str, list[int]] = {}

    for r in results:
        role = "server"  # default
        match = catalog_matches.get(r.id)
        if match:
            role = match.get("role", "server")
        else:
            # Infer from ports
            port_nums = _get_port_numbers(r)
            if 8006 in port_nums:
                role = "hypervisor"
            elif 8443 in port_nums:
                role = "controller"
            elif 8060 in port_nums:
                role = "nas"
            elif any(p in port_nums for p in (80, 443, 8080)):
                role = "server"  # generic server with web ports

        roles.setdefault(role, []).append(r.id)

    return roles
