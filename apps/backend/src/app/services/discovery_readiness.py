"""Discovery capability model + runtime detection.

Answers "what can discovery do right now?" as a small, explicit set of
capabilities, each in exactly one state. Shared verbatim by the scan runner,
the readiness API, and (Phase 3) the in-app Readiness panel.
"""

import ipaddress
import logging
import re
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


def log_discovery_readiness_at_startup() -> None:
    """Emit a loud log line per non-ready capability so degraded discovery is
    visible at boot, never discovered only at scan time."""
    caps = get_discovery_readiness()
    degraded = [c for c in caps if c.state != CapState.READY]
    if not degraded:
        logger.info("Discovery readiness: all capabilities ready.")
        return
    for c in degraded:
        logger.warning(
            "Discovery readiness: %s is %s — %s",
            c.key,
            c.state.value,
            c.explanation,
        )


# ── Per-capability auto-heal metadata (read-time join against the worker audit log) ──

# discovery_reconciler.py writes one worker-audit entry per heal attempt, keyed by
# entity_name. arp_l2/lan_adjacency share a single Class-2 action pair
# (enable_lan_discovery / disable_lan_discovery), so both map to the one
# "lan_discovery" entity_name the reconciler actually logs under — matches
# discovery_reconciler.py's _CLASS1_ACTIONS keys and its Class-2 literal verbatim.
_HEAL_ENTITY_NAME_BY_CAPABILITY = {
    "nmap_present": "nmap_present",
    "nmap_raw": "nmap_raw",
    "arp_l2": "lan_discovery",
    "lan_adjacency": "lan_discovery",
}

_HEAL_ERROR_DETAIL_RE = re.compile(r"error=(.*)$")


def _extract_heal_error_message(details: str | None) -> str | None:
    """Pull the `<msg>` out of a `"capability=<key> error=<msg>"` audit-log
    details string. Falls back to the raw string when the pattern isn't found,
    so an unexpected details format never silently loses the error."""
    if details is None:
        return None
    match = _HEAL_ERROR_DETAIL_RE.search(details)
    if match:
        return match.group(1).strip()
    return details


def get_capability_heal_metadata(db, capability_key: str) -> dict:
    """Read-time join: look up the most recent auto-heal success/failure for
    *capability_key* in the worker audit log. Pure read — writes nothing."""
    from sqlalchemy import select

    from app.db.models import Log

    entity_name = _HEAL_ENTITY_NAME_BY_CAPABILITY.get(capability_key)
    if entity_name is None:
        return {"last_healed_at": None, "last_error": None}

    base = select(Log).where(
        Log.category == "worker",
        Log.entity_type == "discovery_capability",
        Log.entity_name == entity_name,
    )
    last_success = db.execute(
        base.where(Log.action.like("discovery_auto_heal_%"))
        .where(~Log.action.like("%_failed"))
        .order_by(Log.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()
    last_failure = db.execute(
        base.where(Log.action.like("%_failed")).order_by(Log.timestamp.desc()).limit(1)
    ).scalar_one_or_none()

    last_healed_at = last_success.timestamp.isoformat() if last_success else None
    last_error = None
    if last_failure is not None and (
        last_success is None or last_failure.timestamp > last_success.timestamp
    ):
        last_error = _extract_heal_error_message(last_failure.details)
    return {"last_healed_at": last_healed_at, "last_error": last_error}
