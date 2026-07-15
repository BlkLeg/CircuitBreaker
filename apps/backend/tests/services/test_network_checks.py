"""Tests for hostile-network checks — all I/O mocked; errors must yield unknown."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import network_checks
from app.services.threat_feed import ThreatFeed

# ── captive portal ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_captive_portal_204_is_ok():
    with patch.object(network_checks, "_fetch_status", AsyncMock(return_value=(204, False))):
        result = await network_checks.check_captive_portal()
    assert result["check_id"] == "captive_portal"
    assert result["status"] == "ok"
    assert result["detected_at"]


@pytest.mark.asyncio
async def test_captive_portal_redirect_is_warning():
    with patch.object(network_checks, "_fetch_status", AsyncMock(return_value=(302, True))):
        result = await network_checks.check_captive_portal()
    assert result["status"] == "warning"


@pytest.mark.asyncio
async def test_captive_portal_non_204_is_warning():
    with patch.object(network_checks, "_fetch_status", AsyncMock(return_value=(200, False))):
        result = await network_checks.check_captive_portal()
    assert result["status"] == "warning"


@pytest.mark.asyncio
async def test_captive_portal_error_is_unknown_never_hostile():
    with patch.object(
        network_checks,
        "_fetch_status",
        AsyncMock(side_effect=httpx.ConnectError("no route")),
    ):
        result = await network_checks.check_captive_portal()
    assert result["status"] == "unknown"


# ── dns tamper ────────────────────────────────────────────────────────────────


def _canary_resolver(mapping):
    async def _resolve(domain):
        value = mapping.get(domain)
        if value is None:
            raise OSError("resolution failed")
        return value

    return _resolve


@pytest.mark.asyncio
async def test_dns_tamper_matching_answers_is_ok():
    mapping = {domain: set(expected) for domain, expected in network_checks.DNS_CANARIES.items()}
    with patch.object(network_checks, "_resolve_ips", _canary_resolver(mapping)):
        result = await network_checks.check_dns_tamper()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_dns_tamper_mismatch_is_critical():
    mapping = {domain: {"10.66.6.1"} for domain in network_checks.DNS_CANARIES}
    with patch.object(network_checks, "_resolve_ips", _canary_resolver(mapping)):
        result = await network_checks.check_dns_tamper()
    assert result["status"] == "critical"
    assert "10.66.6.1" in result["evidence"]


@pytest.mark.asyncio
async def test_dns_tamper_no_resolution_is_unknown():
    with patch.object(network_checks, "_resolve_ips", _canary_resolver({})):
        result = await network_checks.check_dns_tamper()
    assert result["status"] == "unknown"


# ── dns filtering absent ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dns_filtering_skipped_when_feed_unavailable():
    result = await network_checks.check_dns_filtering(ThreatFeed(available=False))
    assert result["check_id"] == "dns_filtering_absent"
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_dns_filtering_absent_when_malware_domain_resolves():
    feed = ThreatFeed(malware={"evil.example"})
    with patch.object(
        network_checks, "_resolve_ips", _canary_resolver({"evil.example": {"93.184.216.34"}})
    ):
        result = await network_checks.check_dns_filtering(feed)
    assert result["status"] == "info"


@pytest.mark.asyncio
async def test_dns_filtering_present_when_domains_blocked():
    feed = ThreatFeed(malware={"evil.example", "bad.example"})
    # NXDOMAIN for one, sinkholed 0.0.0.0 for the other ⇒ filtering is working
    with patch.object(
        network_checks, "_resolve_ips", _canary_resolver({"bad.example": {"0.0.0.0"}})
    ):
        result = await network_checks.check_dns_filtering(feed)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_dns_filtering_empty_malware_set_is_unknown():
    result = await network_checks.check_dns_filtering(ThreatFeed(malware=set()))
    assert result["status"] == "unknown"


# ── run_all_checks ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_all_checks_returns_three_results():
    feed = ThreatFeed(malware={"evil.example"})
    mapping = {domain: set(expected) for domain, expected in network_checks.DNS_CANARIES.items()}
    mapping["evil.example"] = {"93.184.216.34"}
    with (
        patch.object(network_checks, "_fetch_status", AsyncMock(return_value=(204, False))),
        patch.object(network_checks, "_resolve_ips", _canary_resolver(mapping)),
    ):
        results = await network_checks.run_all_checks(feed)
    by_id = {r["check_id"]: r for r in results}
    assert set(by_id) == {"captive_portal", "dns_tamper", "dns_filtering_absent"}
    assert by_id["captive_portal"]["status"] == "ok"
    assert by_id["dns_tamper"]["status"] == "ok"
    assert by_id["dns_filtering_absent"]["status"] == "info"


@pytest.mark.asyncio
async def test_run_all_checks_dns_down_marks_filtering_unknown():
    # DNS entirely broken: tamper is unknown, so filtering must not claim "ok"
    feed = ThreatFeed(malware={"evil.example"})
    with (
        patch.object(network_checks, "_fetch_status", AsyncMock(return_value=(204, False))),
        patch.object(network_checks, "_resolve_ips", _canary_resolver({})),
    ):
        results = await network_checks.run_all_checks(feed)
    by_id = {r["check_id"]: r for r in results}
    assert by_id["dns_tamper"]["status"] == "unknown"
    assert by_id["dns_filtering_absent"]["status"] == "unknown"
