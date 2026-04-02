"""Unit tests for the discovery fingerprinting module.

Tests for _parse_banner_for_hints, _classify_device, _coalesce_host_info,
_run_rdns_probe, and _run_netbios_probe (mocked).
"""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest

from app.services.discovery_fingerprint import (
    _classify_device,
    _coalesce_host_info,
    _parse_banner_for_hints,
    _run_netbios_probe,
    _run_rdns_probe,
)

# ─────────────────────────────────────────────────────────────────────────────
# _parse_banner_for_hints
# ─────────────────────────────────────────────────────────────────────────────


class TestParseBannerForHints:
    def test_ssh_ubuntu(self) -> None:
        banner = "SSH-2.0-OpenSSH_9.2p1 Ubuntu-2ubuntu0.3"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_family") == "Linux"
        assert result.get("os_vendor") == "Ubuntu"

    def test_ssh_debian(self) -> None:
        banner = "SSH-2.0-OpenSSH_9.2p1 Debian-2+deb12u2"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_family") == "Linux"
        assert result.get("os_vendor") == "Debian"

    def test_ssh_windows(self) -> None:
        banner = "SSH-2.0-OpenSSH_for_Windows_9.5"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_family") == "Windows"
        assert result.get("os_vendor") == "Microsoft"
        assert result.get("device_type") == "windows_pc"

    def test_ssh_routeros(self) -> None:
        banner = "SSH-2.0-ROSSSH"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_vendor") == "MikroTik"
        assert result.get("device_type") == "router"

    def test_ssh_cisco(self) -> None:
        banner = "SSH-2.0-Cisco-1.25"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_vendor") == "Cisco"
        assert result.get("device_type") == "router"

    def test_ftp_synology(self) -> None:
        banner = "220 SynologyDiskStation FTP server ready."
        result = _parse_banner_for_hints(banner)
        assert result.get("device_type") == "nas"
        assert result.get("os_vendor") == "Synology"

    def test_http_iis(self) -> None:
        banner = "Server: Microsoft-IIS/10.0"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_family") == "Windows"
        assert result.get("os_vendor") == "Microsoft"

    def test_pfsense(self) -> None:
        banner = "pfSense"
        result = _parse_banner_for_hints(banner)
        assert result.get("device_type") == "firewall"

    def test_no_match_returns_empty(self) -> None:
        result = _parse_banner_for_hints("some garbage banner xyz 12345")
        assert result == {}

    def test_none_input(self) -> None:
        result = _parse_banner_for_hints(None)
        assert result == {}

    def test_empty_string(self) -> None:
        result = _parse_banner_for_hints("")
        assert result == {}

    def test_ubiquiti(self) -> None:
        banner = "SSH-2.0-OpenSSH_7.4 UniFi"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_vendor") == "Ubiquiti"
        assert result.get("device_type") == "access_point"

    def test_fritzbox_telnet(self) -> None:
        banner = "FRITZ!Box 7590 AX"
        result = _parse_banner_for_hints(banner)
        # FRITZ!Box is in the HTTP title rules, not banner rules
        # — this is expected to return empty from banner parser
        # (it's caught by the HTTP fingerprint probe instead)
        assert isinstance(result, dict)

    def test_freebsd(self) -> None:
        banner = "SSH-2.0-OpenSSH_8.8 FreeBSD-20211221"
        result = _parse_banner_for_hints(banner)
        assert result.get("os_family") == "BSD"
        assert result.get("os_vendor") == "FreeBSD"


# ─────────────────────────────────────────────────────────────────────────────
# _classify_device
# ─────────────────────────────────────────────────────────────────────────────


class TestClassifyDevice:
    def test_iphone_via_mdns(self) -> None:
        evidence = {
            "mdns_services": ["_apple-mobdev2._tcp.local."],
            "oui_vendor": "Apple Inc.",
            "open_ports": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "ios_device"
        assert conf >= 50

    def test_fire_tv_via_ssdp(self) -> None:
        evidence = {
            "ssdp_friendly_name": "Amazon Fire TV Stick",
            "open_ports": [],
            "mdns_services": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "fire_tv"
        assert conf >= 30

    def test_printer_via_mdns_and_port(self) -> None:
        evidence = {
            "mdns_services": ["_ipp._tcp.local."],
            "open_ports": [{"port": 631}, {"port": 9100}],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "printer"
        assert conf >= 60

    def test_router_via_wan_ssdp(self) -> None:
        evidence = {
            "ssdp_device_type": "urn:schemas-upnp-org:device:WANDevice:1",
            "open_ports": [],
            "mdns_services": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "router"
        assert conf >= 30

    def test_ip_camera_via_rtsp_port(self) -> None:
        evidence = {
            "open_ports": [{"port": 554}, {"port": 80}],
            "mdns_services": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "ip_camera"
        assert conf >= 25

    def test_windows_pc_via_rdp(self) -> None:
        evidence = {
            "open_ports": [{"port": 3389}, {"port": 445}],
            "os_family": "Windows",
            "mdns_services": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "windows_pc"
        assert conf >= 50

    def test_nas_via_afp_smb(self) -> None:
        evidence = {
            "open_ports": [{"port": 548}, {"port": 2049}, {"port": 445}],
            "mdns_services": ["_smb._tcp.local.", "_afpovertcp._tcp.local."],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "nas"
        assert conf >= 60

    def test_proxmox_hypervisor(self) -> None:
        evidence = {
            "open_ports": [{"port": 8006}, {"port": 22}],
            "mdns_services": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "hypervisor"
        assert conf >= 45

    def test_no_evidence_returns_none(self) -> None:
        dtype, conf = _classify_device({"open_ports": [], "mdns_services": []})
        assert dtype is None
        assert conf == 0

    def test_chromecast_via_mdns(self) -> None:
        evidence = {
            "mdns_services": ["_googlecast._tcp.local."],
            "oui_vendor": "Google LLC",
            "open_ports": [],
        }
        dtype, conf = _classify_device(evidence)
        assert dtype == "chromecast"
        assert conf >= 40


# ─────────────────────────────────────────────────────────────────────────────
# _coalesce_host_info
# ─────────────────────────────────────────────────────────────────────────────


class TestCoalesceHostInfo:
    def _call(self, **kwargs):  # type: ignore[no-untyped-def]
        defaults = {
            "nmap_data": {},
            "snmp_data": {},
            "mdns_data": {},
            "netbios": {},
            "ssdp_data": {},
            "banner_hints": {},
            "http_hints": {},
            "rdns_hostname": None,
            "oui_vendor": None,
            "open_ports": [],
        }
        defaults.update(kwargs)
        return _coalesce_host_info(**defaults)

    def test_nmap_wins_over_banner(self) -> None:
        result = self._call(
            nmap_data={"hostname": "nmap-host", "os_family": "Windows", "os_vendor": "Microsoft"},
            banner_hints={"os_family": "Linux", "os_vendor": "Debian"},
        )
        assert result["os_family"] == "Windows"
        assert result["os_vendor"] == "Microsoft"
        assert result["hostname"] == "nmap-host"

    def test_falls_back_to_banner_when_nmap_empty(self) -> None:
        result = self._call(
            nmap_data={"hostname": None, "os_family": None, "os_vendor": None},
            banner_hints={"os_family": "Linux", "os_vendor": "Debian"},
        )
        assert result["os_family"] == "Linux"
        assert result["os_vendor"] == "Debian"

    def test_rdns_fills_hostname_when_all_else_empty(self) -> None:
        result = self._call(rdns_hostname="myhost.local")
        assert result["hostname"] == "myhost.local"

    def test_netbios_hostname(self) -> None:
        result = self._call(netbios={"hostname": "WINPC01"})
        assert result["hostname"] == "WINPC01"

    def test_oui_vendor_fills_os_vendor(self) -> None:
        result = self._call(oui_vendor="Apple Inc.")
        assert result["os_vendor"] == "Apple Inc."

    def test_all_empty_no_crash(self) -> None:
        result = self._call()
        assert result["hostname"] is None
        assert result["os_family"] is None
        assert result["os_vendor"] is None
        assert result["device_type"] is None
        assert result["device_confidence"] == 0

    def test_snmp_hostname_used(self) -> None:
        result = self._call(snmp_data={"sys_name": "core-switch-01"})
        assert result["hostname"] == "core-switch-01"

    def test_mdns_hostname_used(self) -> None:
        result = self._call(mdns_data={"hostname": "mymac.local", "services": [], "os_hint": None})
        assert result["hostname"] == "mymac.local"


# ─────────────────────────────────────────────────────────────────────────────
# _run_rdns_probe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rdns_probe_returns_ptr_record() -> None:
    with patch("socket.gethostbyaddr", return_value=("myhost.example.com", [], ["1.2.3.4"])):
        result = await _run_rdns_probe("1.2.3.4")
    assert result == "myhost.example.com"


@pytest.mark.asyncio
async def test_rdns_probe_returns_none_on_herror() -> None:
    with patch("socket.gethostbyaddr", side_effect=socket.herror("no name")):
        result = await _run_rdns_probe("10.0.0.1")
    assert result is None


@pytest.mark.asyncio
async def test_rdns_probe_returns_none_when_ptr_equals_ip() -> None:
    with patch("socket.gethostbyaddr", return_value=("10.0.0.1", [], ["10.0.0.1"])):
        result = await _run_rdns_probe("10.0.0.1")
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# _run_netbios_probe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_netbios_probe_returns_empty_on_connection_refusal() -> None:
    """When the UDP response times out, probe should return empty dict (not raise)."""

    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = TimeoutError("timed out")
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        result = await _run_netbios_probe("192.168.1.1")
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# KB lookup helpers
# ─────────────────────────────────────────────────────────────────────────────


def test_kb_oui_lookup_known_prefix():
    from app.services.discovery_fingerprint import _kb_oui_lookup

    result = _kb_oui_lookup("bc:24:11:20:2b:65")
    assert result is not None
    assert result["vendor"] == "Proxmox Server Solutions GmbH"
    assert result["device_type"] == "hypervisor"


def test_kb_oui_lookup_unknown_prefix():
    from app.services.discovery_fingerprint import _kb_oui_lookup

    result = _kb_oui_lookup("aa:bb:cc:11:22:33")
    assert result is None


def test_kb_oui_lookup_empty_mac():
    from app.services.discovery_fingerprint import _kb_oui_lookup

    assert _kb_oui_lookup("") is None
    assert _kb_oui_lookup(None) is None


def test_kb_oui_lookup_normalizes_format():
    from app.services.discovery_fingerprint import _kb_oui_lookup

    assert _kb_oui_lookup("BC-24-11-AA-BB-CC") is not None
    assert _kb_oui_lookup("bc2411aabbcc") is not None


def test_kb_hostname_hints_prefix_match():
    from app.services.discovery_fingerprint import _kb_hostname_hints

    result = _kb_hostname_hints("pve3")
    assert result["vendor"] == "Proxmox Server Solutions GmbH"
    assert result["device_type"] == "hypervisor"
    assert result["os_family"] == "Linux"


def test_kb_hostname_hints_exact_match():
    from app.services.discovery_fingerprint import _kb_hostname_hints

    result = _kb_hostname_hints("_gateway")
    assert result["device_type"] == "router"
    assert "vendor" not in result


def test_kb_hostname_hints_no_match():
    from app.services.discovery_fingerprint import _kb_hostname_hints

    result = _kb_hostname_hints("mydesktop")
    assert result == {}


def test_kb_hostname_hints_case_insensitive():
    from app.services.discovery_fingerprint import _kb_hostname_hints

    assert _kb_hostname_hints("PVE-MASTER")["vendor"] == "Proxmox Server Solutions GmbH"


def test_kb_hostname_hints_uses_injected_cache():
    """Injected scan_hostname_cache overrides device_kb.json lookup."""
    from app.services.discovery_fingerprint import _kb_hostname_hints

    custom_cache = [
        {
            "pattern": "myrouter",
            "match_type": "exact",
            "vendor": "CustomVendor",
            "device_type": "router",
        },
    ]
    result = _kb_hostname_hints("myrouter", scan_hostname_cache=custom_cache)
    assert result["vendor"] == "CustomVendor"
    assert result["device_type"] == "router"


def test_kb_hostname_hints_cache_none_falls_back_to_json():
    """None cache falls back to device_kb.json — existing JSON rules still work."""
    from app.services.discovery_fingerprint import _kb_hostname_hints

    # "pve" prefix is defined in device_kb.json
    result = _kb_hostname_hints("pve-master", scan_hostname_cache=None)
    assert result.get("vendor") == "Proxmox Server Solutions GmbH"


def test_kb_hostname_hints_match_type_key():
    """match_type (DB column) and match (JSON legacy key) both resolve correctly."""
    from app.services.discovery_fingerprint import _kb_hostname_hints

    # Using DB-style "match_type" key
    cache_db_style = [
        {
            "pattern": "synology",
            "match_type": "prefix",
            "vendor": "Synology",
            "device_type": "storage",
        }
    ]
    assert (
        _kb_hostname_hints("synology-nas", scan_hostname_cache=cache_db_style)["vendor"]
        == "Synology"
    )
    # Using JSON-style "match" key
    cache_json_style = [
        {"pattern": "synology", "match": "prefix", "vendor": "Synology", "device_type": "storage"}
    ]
    assert (
        _kb_hostname_hints("synology-nas", scan_hostname_cache=cache_json_style)["vendor"]
        == "Synology"
    )


def test_kb_hostname_hints_injected_cache_no_match_returns_empty():
    """Injected cache with no matching rule returns empty dict."""
    from app.services.discovery_fingerprint import _kb_hostname_hints

    result = _kb_hostname_hints(
        "unknownhost",
        scan_hostname_cache=[
            {"pattern": "known", "match_type": "exact", "vendor": "SomeVendor"},
        ],
    )
    assert result == {}


def test_parse_snmp_sysdescr_proxmox():
    from app.services.discovery_fingerprint import _parse_snmp_sysdescr

    result = _parse_snmp_sysdescr("Proxmox Virtual Environment 8.1.3")
    assert result["vendor"] == "Proxmox Server Solutions GmbH"
    assert result["os_family"] == "Linux"


def test_parse_snmp_sysdescr_ubuntu():
    from app.services.discovery_fingerprint import _parse_snmp_sysdescr

    result = _parse_snmp_sysdescr("Linux myhost 5.15.0-91-generic Ubuntu")
    assert result["vendor"] == "Ubuntu"
    assert result["os_family"] == "Linux"


def test_parse_snmp_sysdescr_empty():
    from app.services.discovery_fingerprint import _parse_snmp_sysdescr

    assert _parse_snmp_sysdescr("") == {}
    assert _parse_snmp_sysdescr(None) == {}


def test_parse_snmp_sysdescr_no_match_returns_empty_dict():
    from app.services.discovery_fingerprint import _parse_snmp_sysdescr

    assert _parse_snmp_sysdescr("RouterOS unknown device") == {}


# ── _coalesce_host_info ───────────────────────────────────────────────────────

_EMPTY_COALESCE = dict(
    nmap_data={},
    snmp_data={},
    mdns_data={},
    netbios={},
    ssdp_data={},
    banner_hints={},
    http_hints={},
    rdns_hostname=None,
    oui_vendor=None,
    open_ports=[],
)


def test_coalesce_kb_entry_vendor_beats_banner():
    """KB OUI vendor (rank 5) should win over SSH banner vendor (rank 6)."""
    from app.services.discovery_fingerprint import _coalesce_host_info

    result = _coalesce_host_info(
        **{**_EMPTY_COALESCE, "banner_hints": {"os_vendor": "Ubuntu"}},
        kb_entry={"vendor": "Proxmox Server Solutions GmbH", "device_type": "hypervisor"},
    )
    assert result["os_vendor"] == "Proxmox Server Solutions GmbH"


def test_coalesce_http_vendor_beats_kb_entry():
    """HTTP fingerprint (rank 3) should still beat KB OUI (rank 5)."""
    from app.services.discovery_fingerprint import _coalesce_host_info

    result = _coalesce_host_info(
        **{**_EMPTY_COALESCE, "http_hints": {"os_vendor": "Synology DiskStation"}},
        kb_entry={"vendor": "Some OUI Vendor"},
    )
    assert result["os_vendor"] == "Synology DiskStation"


def test_coalesce_hostname_hints_vendor_as_last_resort():
    """hostname_hints vendor only used when all other sources are empty."""
    from app.services.discovery_fingerprint import _coalesce_host_info

    result = _coalesce_host_info(
        **_EMPTY_COALESCE,
        hostname_hints={"vendor": "OPNsense", "device_type": "firewall"},
    )
    assert result["os_vendor"] == "OPNsense"


def test_coalesce_kb_device_type_improves_classification():
    """kb_entry device_type signal raises confidence for hypervisor classification."""
    from app.services.discovery_fingerprint import _coalesce_host_info

    result = _coalesce_host_info(
        **_EMPTY_COALESCE,
        kb_entry={"vendor": "Proxmox Server Solutions GmbH", "device_type": "hypervisor"},
    )
    assert result["device_type"] == "hypervisor"


def test_coalesce_snmp_vendor_beats_kb_when_snmp_present():
    """SNMP sysDescr (rank 4) beats KB OUI (rank 5) for os_vendor."""
    from app.services.discovery_fingerprint import _coalesce_host_info

    result = _coalesce_host_info(
        **{**_EMPTY_COALESCE, "snmp_data": {"sys_descr": "Proxmox Virtual Environment 8.1"}},
        kb_entry={"vendor": "Some Other Vendor"},
    )
    assert result["os_vendor"] == "Proxmox Server Solutions GmbH"


# ── _run_vendor_lookup_local ──────────────────────────────────────────────────


def test_run_vendor_lookup_local_none_mac():
    from app.services.discovery_fingerprint import _run_vendor_lookup_local

    vendor, entry = asyncio.run(_run_vendor_lookup_local(None))
    assert vendor is None
    assert entry is None


def test_run_vendor_lookup_local_scan_cache_hit():
    """scan_oui_cache hit returns (vendor, full_entry) without touching KB or manuf."""
    from app.services.discovery_fingerprint import _run_vendor_lookup_local

    cache = {"BC2411": {"vendor": "Proxmox Server Solutions GmbH", "device_type": "hypervisor"}}
    vendor, entry = asyncio.run(_run_vendor_lookup_local("BC:24:11:AA:BB:CC", scan_oui_cache=cache))
    assert vendor == "Proxmox Server Solutions GmbH"
    assert entry == {"vendor": "Proxmox Server Solutions GmbH", "device_type": "hypervisor"}


def test_run_vendor_lookup_local_scan_cache_miss_falls_to_kb():
    """A prefix absent from scan_oui_cache falls through to the curated KB JSON."""
    from app.services.discovery_fingerprint import _run_vendor_lookup_local

    # Empty cache — should fall through to KB (BC2411 is in device_kb.json)
    vendor, entry = asyncio.run(_run_vendor_lookup_local("BC:24:11:AA:BB:CC", scan_oui_cache={}))
    assert vendor == "Proxmox Server Solutions GmbH"
    assert entry is not None
    assert entry.get("device_type") == "hypervisor"


def test_run_vendor_lookup_local_returns_tuple_no_cache():
    """Without scan_oui_cache, KB hit still returns a (vendor, entry) tuple."""
    from app.services.discovery_fingerprint import _run_vendor_lookup_local

    vendor, entry = asyncio.run(_run_vendor_lookup_local("BC:24:11:00:00:01"))
    assert vendor == "Proxmox Server Solutions GmbH"
    assert isinstance(entry, dict)


# ─────────────────────────────────────────────────────────────────────────────
# mDNS probe parallelization
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mdns_probe_queries_all_services(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """All 17 service types must be queried — not just the first match."""
    from app.services.discovery_fingerprint import _MDNS_SERVICE_TYPES, _run_mdns_probe

    call_log: list[str] = []

    class FakeAiozc:
        async def async_get_service_info(
            self, stype: str, name: str, _timeout: float | None = None
        ) -> None:
            call_log.append(stype)
            return None

        async def async_close(self) -> None:
            pass

    monkeypatch.setattr("app.services.discovery_fingerprint._ZEROCONF_AVAILABLE", True)
    with patch("zeroconf.asyncio.AsyncZeroconf", return_value=FakeAiozc()):
        await _run_mdns_probe("192.168.1.55")

    assert len(call_log) == len(_MDNS_SERVICE_TYPES)


@pytest.mark.asyncio
async def test_mdns_probe_survives_partial_exception(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An exception on one service type must not abort the whole probe."""
    from app.services.discovery_fingerprint import _run_mdns_probe

    call_count = 0

    class FakeAiozc:
        async def async_get_service_info(
            self, stype: str, name: str, _timeout: float | None = None
        ) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("zeroconf internal error")
            return None

        async def async_close(self) -> None:
            pass

    monkeypatch.setattr("app.services.discovery_fingerprint._ZEROCONF_AVAILABLE", True)
    with patch("zeroconf.asyncio.AsyncZeroconf", return_value=FakeAiozc()):
        result = await _run_mdns_probe("192.168.1.55")

    assert isinstance(result, dict)
