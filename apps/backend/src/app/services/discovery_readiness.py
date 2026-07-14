"""Discovery capability model + runtime detection.

Answers "what can discovery do right now?" as a small, explicit set of
capabilities, each in exactly one state. Shared verbatim by the scan runner,
the readiness API, and (Phase 3) the in-app Readiness panel.
"""

import ipaddress
import logging
from dataclasses import dataclass
from enum import StrEnum

from app.services.discovery_probes import (
    _arp_available,
    _nmap_os_capable,
    nmap_binary_present,
)

logger = logging.getLogger(__name__)


class CapState(StrEnum):
    READY = "ready"
    AUTO_FIXABLE = "auto-fixable"
    NEEDS_HELPER_ACTION = "needs-helper-action"
    UNAVAILABLE_ON_PLATFORM = "unavailable-on-platform"


@dataclass
class Capability:
    key: str
    title: str
    state: CapState
    explanation: str
    reason_code: str


# Docker default bridge ranges (docker0 + user-defined bridges live in 172.16/12).
_DOCKER_BRIDGE_NET = ipaddress.ip_network("172.16.0.0/12")


def detect_lan_adjacency() -> bool:
    """Best-effort: True if this process is directly on a LAN, not a docker bridge.

    Heuristic: if the only RFC1918 interface addresses fall inside the docker
    bridge range (172.16/12) AND /.dockerenv exists, we're almost certainly a
    bridged container with no L2 reach to the user's LAN. Any interface on a
    192.168/16 or 10/8 address is treated as real LAN adjacency.
    """
    import os
    import socket

    in_container = os.path.exists("/.dockerenv")
    addrs: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addrs.append(str(info[4][0]))
    except Exception:
        pass
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_loopback or not ip.is_private:
            continue
        if ip not in _DOCKER_BRIDGE_NET:
            return True  # on a real LAN (192.168/16 or 10/8)
    # No non-bridge private address found.
    return not in_container


def get_discovery_readiness() -> list[Capability]:
    has_nmap = nmap_binary_present()
    has_raw = _nmap_os_capable()
    has_arp = _arp_available()
    has_lan = detect_lan_adjacency()

    nmap_present = Capability(
        key="nmap_present",
        title="Nmap scanner",
        state=CapState.READY if has_nmap else CapState.AUTO_FIXABLE,
        explanation=(
            "The nmap scanner is installed and available."
            if has_nmap
            else "The nmap binary is missing — discovery cannot actively scan. "
            "It is installed automatically on next start/install."
        ),
        reason_code="nmap_ok" if has_nmap else "nmap_binary_missing",
    )
    nmap_raw = Capability(
        key="nmap_raw",
        title="Fast host discovery & OS detection",
        state=CapState.READY if has_raw else CapState.AUTO_FIXABLE,
        explanation=(
            "Raw-socket privilege is available; ICMP/SYN sweeps and OS detection are enabled."
            if has_raw
            else "Raw-socket privilege (CAP_NET_RAW) is missing; nmap falls back "
            "to slower TCP-connect discovery. Granted automatically at startup."
        ),
        reason_code="raw_ok" if has_raw else "raw_priv_missing",
    )
    arp_l2 = Capability(
        key="arp_l2",
        title="ARP / MAC address resolution",
        state=CapState.READY if has_arp else CapState.NEEDS_HELPER_ACTION,
        explanation=(
            "ARP scanning is available; MAC addresses are resolved for LAN hosts."
            if has_arp
            else "ARP scanning is unavailable — MAC resolution and the most "
            "reliable LAN sweep are off. Enable LAN discovery in Discovery Settings."
        ),
        reason_code="arp_ok" if has_arp else "arp_unavailable",
    )
    lan_adjacency = Capability(
        key="lan_adjacency",
        title="Direct LAN reachability",
        state=CapState.READY if has_lan else CapState.NEEDS_HELPER_ACTION,
        explanation=(
            "This instance is directly on your LAN."
            if has_lan
            else "This instance appears to be on a Docker bridge, not your LAN, "
            "so Layer-2 discovery (ARP) can't reach hosts. Enable LAN discovery "
            "in Discovery Settings."
        ),
        reason_code="lan_ok" if has_lan else "bridged_no_l2",
    )
    return [nmap_present, nmap_raw, arp_l2, lan_adjacency]
