"""Hostile-network detections: captive portal, DNS tampering, DNS filtering.

Every check returns ``{"check_id", "status", "evidence", "detected_at"}`` with
status ``ok | info | warning | critical | unknown``. A check that itself errors
reports ``unknown`` — we never fabricate "hostile" from our own failures.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.core.constants import (
    CAPTIVE_PORTAL_CHECK_URL,
    CAPTIVE_PORTAL_EXPECTED_STATUS,
    DNS_CANARIES,
    DNS_FILTERING_SAMPLE_SIZE,
    NETWORK_CHECK_TIMEOUT_S,
)
from app.services.threat_feed import ThreatFeed

logger = logging.getLogger(__name__)

_SINKHOLE_IPS = frozenset({"0.0.0.0", "127.0.0.1", "::", "::1"})


def _build_result(check_id: str, status: str, evidence: str) -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "evidence": evidence,
        "detected_at": datetime.now(UTC).isoformat(),
    }


async def _fetch_status(url: str) -> tuple[int, bool]:
    """GET a URL without following redirects; returns (status_code, is_redirect)."""
    async with httpx.AsyncClient(timeout=NETWORK_CHECK_TIMEOUT_S, follow_redirects=False) as client:
        response = await client.get(url)
        return response.status_code, response.is_redirect


async def _resolve_ips(domain: str) -> set[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(domain, None)
    return {str(sockaddr[0]) for _family, _type, _proto, _canonname, sockaddr in infos}


async def check_captive_portal() -> dict:
    """A generate_204 endpoint answering anything but 204 means interception."""
    check_id = "captive_portal"
    try:
        status_code, is_redirect = await _fetch_status(CAPTIVE_PORTAL_CHECK_URL)
    except httpx.HTTPError as exc:
        logger.warning("[network_checks] captive portal check errored: %s", exc)
        return _build_result(check_id, "unknown", f"check failed: {exc}")
    if status_code == CAPTIVE_PORTAL_EXPECTED_STATUS and not is_redirect:
        return _build_result(check_id, "ok", "generate_204 returned 204")
    return _build_result(
        check_id, "warning", f"generate_204 returned {status_code} (redirect={is_redirect})"
    )


async def check_dns_tamper() -> dict:
    """Canary domains with known-stable answers; a mismatch means DNS tampering."""
    check_id = "dns_tamper"
    mismatches: list[str] = []
    resolved_any = False
    for domain, expected_ips in DNS_CANARIES.items():
        try:
            answers = await _resolve_ips(domain)
        except OSError as exc:
            logger.warning("[network_checks] canary %s did not resolve: %s", domain, exc)
            continue
        resolved_any = True
        if not (answers & expected_ips):
            mismatches.append(f"{domain} resolved to {sorted(answers)}")
    if mismatches:
        return _build_result(check_id, "critical", "; ".join(mismatches))
    if not resolved_any:
        return _build_result(check_id, "unknown", "no canary domain resolved")
    return _build_result(check_id, "ok", "canary answers match known-stable IPs")


async def check_dns_filtering(feed: ThreatFeed) -> dict:
    """Feed-powered: known-bad domains that resolve normally ⇒ no DNS filtering."""
    check_id = "dns_filtering_absent"
    if not feed.available or not feed.malware:
        return _build_result(check_id, "unknown", "threat feed unavailable — check skipped")
    sample = sorted(feed.malware)[:DNS_FILTERING_SAMPLE_SIZE]
    for domain in sample:
        try:
            answers = await _resolve_ips(domain)
        except OSError:
            continue  # NXDOMAIN ⇒ blocked upstream — that's filtering working
        if answers - _SINKHOLE_IPS:
            return _build_result(
                check_id, "info", f"known-bad domain {domain} resolves — no DNS-level blocking"
            )
    return _build_result(check_id, "ok", f"sampled {len(sample)} known-bad domains, all blocked")


async def run_all_checks(feed: ThreatFeed) -> list[dict]:
    """Run every network check; if DNS is entirely down, filtering stays unknown."""
    captive_portal, dns_tamper = await asyncio.gather(check_captive_portal(), check_dns_tamper())
    if dns_tamper["status"] == "unknown":
        dns_filtering = _build_result(
            "dns_filtering_absent", "unknown", "DNS unavailable — check skipped"
        )
    else:
        dns_filtering = await check_dns_filtering(feed)
    return [captive_portal, dns_tamper, dns_filtering]
