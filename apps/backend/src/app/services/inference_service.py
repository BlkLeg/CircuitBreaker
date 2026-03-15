from __future__ import annotations

import logging
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# InferredAnnotation
# ---------------------------------------------------------------------------


@dataclass
class InferredAnnotation:
    vendor: str | None = None
    role: str | None = None
    vendor_icon_slug: str | None = None
    confidence: float = 0.0
    signals_used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OUIResolver
# ---------------------------------------------------------------------------


class OUIResolver:
    _OUI_OVERRIDES: dict[str, str] = {
        "DCA632": "Raspberry Pi",
        "B827EB": "Raspberry Pi",
        "E45F01": "Raspberry Pi",
        "DC44B6": "Raspberry Pi",
        "244A3C": "Ubiquiti",
        "FCECDA": "Ubiquiti",
        "802AA8": "Ubiquiti",
        "78D2E6": "Synology",
        "001132": "Synology",
        "00113D": "QNAP",
        "243C95": "QNAP",
        "001D0F": "QNAP",
        "000E6B": "Dell",
        "D4BE97": "Dell",
        "00215A": "Dell",
        "00248C": "HP",
        "3CD92B": "HP",
        "001708": "HP",
        "000C29": "VMware",
        "005056": "VMware",
        "0A0027": "VirtualBox",
        "080027": "VirtualBox",
    }

    _VENDOR_TO_ICON: dict[str, str] = {
        "raspberry": "raspberrypi",
        "ubiquiti": "ubiquiti",
        "synology": "synology",
        "qnap": "qnap",
        "dell": "dell",
        "hp": "hp",
        "hewlett": "hp",
        "vmware": "vmware",
        "virtualbox": "virtualbox",
        "proxmox": "proxmox",
        "cisco": "cisco",
        "aruba": "aruba",
        "mikrotik": "mikrotik",
        "pfsense": "pfsense",
        "opnsense": "opnsense",
        "apc": "apc",
        "cyberpower": "cyberpower",
    }

    def lookup(self, mac: str | None) -> str | None:
        if mac is None:
            return None
        try:
            # Normalise to uppercase hex, no separators
            normalised = mac.upper().replace(":", "").replace("-", "").replace(".", "")
            if len(normalised) < 6:
                return None
            oui = normalised[:6]
            # Check overrides first
            if oui in self._OUI_OVERRIDES:
                return self._OUI_OVERRIDES[oui]
            # Fall back to netaddr
            try:
                import netaddr

                reg = netaddr.EUI(mac).oui.registration()
                return reg.org if reg and reg.org else None
            except Exception:
                return None
        except Exception:
            return None

    def icon_slug(self, vendor: str | None) -> str | None:
        if vendor is None:
            return None
        vendor_lower = vendor.lower()
        for key, slug in self._VENDOR_TO_ICON.items():
            if key in vendor_lower:
                return slug
        return None


# ---------------------------------------------------------------------------
# Hostname inference
# ---------------------------------------------------------------------------

_HOSTNAME_RULES: list[tuple[str, dict]] = [
    ("proxmox", {"role": "hypervisor", "vendor_icon_slug": "proxmox"}),
    ("pve", {"role": "hypervisor", "vendor_icon_slug": "proxmox"}),
    ("esxi", {"role": "hypervisor", "vendor_icon_slug": "vmware"}),
    ("vcenter", {"role": "hypervisor", "vendor_icon_slug": "vmware"}),
    ("unifi", {"role": "access_point", "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("usg", {"role": "router", "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("udm", {"role": "router", "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("sw-", {"role": "switch"}),
    ("switch", {"role": "switch"}),
    ("rt-", {"role": "router"}),
    ("router", {"role": "router"}),
    ("gateway", {"role": "router"}),
    ("gw-", {"role": "router"}),
    ("nas", {"role": "storage"}),
    ("synology", {"role": "storage", "vendor": "Synology", "vendor_icon_slug": "synology"}),
    ("qnap", {"role": "storage", "vendor": "QNAP", "vendor_icon_slug": "qnap"}),
    ("truenas", {"role": "storage"}),
    ("freenas", {"role": "storage"}),
    ("rpi-", {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("-rpi-", {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("rpi.", {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("raspberrypi", {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("ap-", {"role": "access_point"}),
    ("-ap.", {"role": "access_point"}),
    ("ups", {"role": "ups"}),
    ("pfsense", {"role": "router", "vendor_icon_slug": "pfsense"}),
    ("opnsense", {"role": "router", "vendor_icon_slug": "opnsense"}),
    ("pihole", {"role": "server", "vendor_icon_slug": "raspberrypi"}),
    ("homeassistant", {"role": "server"}),
]


def _infer_from_hostname(hostname: str | None) -> dict:
    if hostname is None:
        return {}
    hostname_lower = hostname.lower()
    for substring, attrs in _HOSTNAME_RULES:
        if substring in hostname_lower:
            return dict(attrs)
    return {}


# ---------------------------------------------------------------------------
# Port inference
# ---------------------------------------------------------------------------


def _infer_from_ports(ports: list | None) -> dict:
    if not ports:
        return {}
    try:
        port_nums: set[int] = set()
        for p in ports:
            if isinstance(p, dict) and "port" in p:
                port_nums.add(int(p["port"]))

        if not port_nums:
            return {}

        result: dict = {}

        if 8006 in port_nums:
            result["role"] = "hypervisor"
            result["vendor_icon_slug"] = "proxmox"
        elif {22, 443}.issubset(port_nums):
            result["role"] = "server"
        elif port_nums == {80}:
            result["role"] = "misc"
        elif 554 in port_nums:
            result["role"] = "misc"

        if 161 in port_nums:
            result["snmp_capable"] = True

        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

_BASE_SCORES: dict[str, float] = {
    "mac_oui": 0.40,
    "hostname": 0.50,
    "port": 0.30,
}


def _compute_confidence(signals_used: list[str], signals_agree: bool) -> float:
    n = len(signals_used)
    if n == 0:
        return 0.0
    if n == 1:
        return _BASE_SCORES.get(signals_used[0], 0.30)
    if n >= 3 and signals_agree:
        return 1.00
    if signals_agree:
        return 0.75
    # Multiple signals disagreeing
    scores = [_BASE_SCORES.get(s, 0.30) for s in signals_used]
    return max(scores) + 0.10


# ---------------------------------------------------------------------------
# Module-level resolver instance
# ---------------------------------------------------------------------------

_oui_resolver = OUIResolver()


# ---------------------------------------------------------------------------
# annotate_result
# ---------------------------------------------------------------------------


def annotate_result(scan_result) -> InferredAnnotation:
    mac = getattr(scan_result, "mac_address", None)
    hostname = getattr(scan_result, "hostname", None)
    ports = getattr(scan_result, "open_ports_json", None)

    signals_used: list[str] = []
    role_votes: list[str] = []
    vendor_votes: list[str] = []
    icon_votes: list[str] = []

    # --- MAC OUI signal ---
    oui_vendor: str | None = None
    oui_icon: str | None = None
    if mac:
        oui_vendor = _oui_resolver.lookup(mac)
        if oui_vendor:
            oui_icon = _oui_resolver.icon_slug(oui_vendor)
            signals_used.append("mac_oui")
            vendor_votes.append(oui_vendor)
            if oui_icon:
                icon_votes.append(oui_icon)

    # --- Hostname signal ---
    hostname_attrs: dict = {}
    if hostname:
        hostname_attrs = _infer_from_hostname(hostname)
        if hostname_attrs:
            signals_used.append("hostname")
            if "role" in hostname_attrs:
                role_votes.append(hostname_attrs["role"])
            if "vendor" in hostname_attrs:
                vendor_votes.append(hostname_attrs["vendor"])
            if "vendor_icon_slug" in hostname_attrs:
                icon_votes.append(hostname_attrs["vendor_icon_slug"])

    # --- Port signal ---
    port_attrs: dict = {}
    if ports is not None:
        port_attrs = _infer_from_ports(ports)
        if port_attrs:
            signals_used.append("port")
            if "role" in port_attrs:
                role_votes.append(port_attrs["role"])
            if "vendor_icon_slug" in port_attrs:
                icon_votes.append(port_attrs["vendor_icon_slug"])

    # --- Build annotation (first vote wins) ---
    final_role = role_votes[0] if role_votes else None
    final_vendor = vendor_votes[0] if vendor_votes else None
    final_icon = icon_votes[0] if icon_votes else None

    # Signals agree if all role votes are the same, OR majority agree
    from collections import Counter

    unique_roles = set(role_votes)
    if len(unique_roles) <= 1:
        roles_agree = True
    elif len(role_votes) >= 2:
        most_common_count = Counter(role_votes).most_common(1)[0][1]
        roles_agree = most_common_count >= 2
    else:
        roles_agree = False
    confidence = _compute_confidence(signals_used, roles_agree)

    return InferredAnnotation(
        vendor=final_vendor,
        role=final_role,
        vendor_icon_slug=final_icon,
        confidence=confidence,
        signals_used=signals_used,
    )
