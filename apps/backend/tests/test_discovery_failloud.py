from unittest.mock import patch

import app.services.discovery_service as ds
from app.services.discovery_readiness import Capability, CapState


def _cap(key, state):
    return Capability(key=key, title=key, state=state, explanation="x", reason_code="x")


def test_scan_blocks_loudly_when_nmap_absent():
    caps = [
        _cap("nmap_present", CapState.AUTO_FIXABLE),
        _cap("nmap_raw", CapState.AUTO_FIXABLE),
        _cap("arp_l2", CapState.NEEDS_HELPER_ACTION),
        _cap("lan_adjacency", CapState.READY),
    ]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["nmap"])
    assert blocked is True
    assert "nmap" in reason.lower()


def test_scan_allowed_when_nmap_ready():
    caps = [
        _cap("nmap_present", CapState.READY),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["nmap"])
    assert blocked is False
    assert reason == ""


def test_gate_ignored_for_non_nmap_scan():
    caps = [_cap("nmap_present", CapState.AUTO_FIXABLE)]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["docker"])
    assert blocked is False
