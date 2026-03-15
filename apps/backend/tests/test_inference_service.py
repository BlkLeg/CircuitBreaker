from __future__ import annotations

from app.services.inference_service import OUIResolver


class TestOUIResolver:
    def test_known_raspberry_pi_oui(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("DC:A6:32:11:22:33")
        assert vendor is not None
        assert "raspberry" in vendor.lower()

    def test_known_ubiquiti_oui(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("24:A4:3C:11:22:33")
        assert vendor is not None
        assert "ubiquiti" in vendor.lower()

    def test_unknown_oui_returns_none(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("FF:FF:FF:00:00:00")
        assert vendor is None

    def test_missing_mac_returns_none(self):
        resolver = OUIResolver()
        assert resolver.lookup(None) is None

    def test_malformed_mac_returns_none(self):
        resolver = OUIResolver()
        assert resolver.lookup("not-a-mac") is None


class TestHostnameInference:
    def test_proxmox_hostname(self):
        from app.services.inference_service import _infer_from_hostname

        assert _infer_from_hostname("pve-node1.local")["role"] == "hypervisor"

    def test_switch_hostname(self):
        from app.services.inference_service import _infer_from_hostname

        assert _infer_from_hostname("sw-core-01")["role"] == "switch"

    def test_nas_hostname(self):
        from app.services.inference_service import _infer_from_hostname

        assert _infer_from_hostname("synology-nas")["role"] == "storage"

    def test_rpi_hostname_no_false_positive(self):
        from app.services.inference_service import _infer_from_hostname

        result = _infer_from_hostname("pipeline-server")
        assert result.get("role") is None

    def test_rpi_hostname_correct(self):
        from app.services.inference_service import _infer_from_hostname

        assert _infer_from_hostname("rpi-kiosk")["role"] == "sbc"

    def test_unknown_hostname_returns_empty(self):
        from app.services.inference_service import _infer_from_hostname

        assert _infer_from_hostname("desktop-abc123") == {}


class TestPortInference:
    def test_proxmox_port(self):
        from app.services.inference_service import _infer_from_ports

        result = _infer_from_ports([{"port": 8006, "protocol": "tcp", "state": "open"}])
        assert result["role"] == "hypervisor"

    def test_server_ports(self):
        from app.services.inference_service import _infer_from_ports

        result = _infer_from_ports([{"port": 22}, {"port": 443}])
        assert result["role"] == "server"

    def test_snmp_device(self):
        from app.services.inference_service import _infer_from_ports

        result = _infer_from_ports([{"port": 161, "protocol": "udp"}])
        assert result.get("snmp_capable") is True

    def test_empty_ports_returns_empty(self):
        from app.services.inference_service import _infer_from_ports

        assert _infer_from_ports([]) == {}

    def test_none_ports_returns_empty(self):
        from app.services.inference_service import _infer_from_ports

        assert _infer_from_ports(None) == {}


class TestAnnotateResult:
    def _make_result(self, mac=None, hostname=None, ports=None):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.mac_address = mac
        r.hostname = hostname
        r.open_ports_json = ports
        return r

    def test_three_signals_high_confidence(self):
        from app.services.inference_service import annotate_result

        r = self._make_result(mac="DC:A6:32:11:22:33", hostname="rpi-kiosk", ports=[{"port": 22}])
        ann = annotate_result(r)
        assert ann.role == "sbc"
        assert ann.vendor == "Raspberry Pi"
        assert ann.vendor_icon_slug == "raspberrypi"
        assert ann.confidence >= 0.75
        assert "mac_oui" in ann.signals_used

    def test_no_signals_zero_confidence(self):
        from app.services.inference_service import annotate_result

        r = self._make_result()
        ann = annotate_result(r)
        assert ann.confidence == 0.0
        assert ann.role is None
        assert ann.signals_used == []

    def test_hostname_only_medium_confidence(self):
        from app.services.inference_service import annotate_result

        r = self._make_result(hostname="proxmox-node")
        ann = annotate_result(r)
        assert ann.role == "hypervisor"
        assert 0.40 <= ann.confidence <= 0.74

    def test_missing_attributes_no_crash(self):
        from unittest.mock import MagicMock

        from app.services.inference_service import annotate_result

        r = MagicMock(spec=[])
        ann = annotate_result(r)
        assert ann.confidence == 0.0
