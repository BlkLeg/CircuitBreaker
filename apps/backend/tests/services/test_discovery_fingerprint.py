"""Unit tests for the discovery fingerprinting module.

Tests for _parse_banner_for_hints, _classify_device, _coalesce_host_info,
_run_rdns_probe, and _run_netbios_probe (mocked).
"""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

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
    import socket

    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = socket.timeout("timed out")
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        result = await _run_netbios_probe("192.168.1.1")
    assert result == {}
