from unittest.mock import patch

from app.services.monitoring.collectors import COLLECTORS, dns_check


def test_dns_registered():
    assert COLLECTORS["dns"] is dns_check.collect_dns


def test_resolve_up():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.1", "192.0.2.2"], 8.5)):
        result = dns_check.collect_dns("example.com", {"record_type": "A"})
    assert result.up is True
    assert result.details == {"records": ["192.0.2.1", "192.0.2.2"]}
    metrics = {s.metric: s.value for s in result.samples}
    assert metrics["avail"] == 1.0
    assert metrics["latency_ms"] == 8.5


def test_expected_value_match():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.1"], 5.0)):
        result = dns_check.collect_dns(
            "example.com", {"record_type": "A", "expected_values": ["192.0.2.1"]}
        )
    assert result.up is True


def test_expected_value_mismatch():
    with patch.object(dns_check, "_resolve", return_value=(["192.0.2.9"], 5.0)):
        result = dns_check.collect_dns(
            "example.com", {"record_type": "A", "expected_values": ["192.0.2.1"]}
        )
    assert result.up is False
    assert "expected" in result.msg


def test_nxdomain_is_down_not_raise():
    with patch.object(dns_check, "_resolve", side_effect=dns_check.DnsLookupError("NXDOMAIN")):
        result = dns_check.collect_dns("nope.invalid", {"record_type": "A"})
    assert result.up is False
    assert result.samples[0].error_reason == "dns_error"
