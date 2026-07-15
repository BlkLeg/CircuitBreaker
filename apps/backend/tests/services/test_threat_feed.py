"""Tests for the pluggable threat feed: parsing, caching, staleness, airgap."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services import threat_feed
from app.services.threat_feed import PublicBlocklistProvider, ThreatFeed

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── parser ────────────────────────────────────────────────────────────────────


def test_parse_hosts_format_extracts_domains_and_skips_localhost():
    domains = threat_feed.parse_blocklist(_fixture_text("blocklist_hosts.txt"))
    assert domains == {"evil-malware.example", "dropper.bad.example", "zero-routed.example"}


def test_parse_abp_format_extracts_domains():
    domains = threat_feed.parse_blocklist(_fixture_text("blocklist_abp.txt"))
    assert domains == {"tracker.example", "ads.metrics.example"}


def test_parse_plain_domain_list_lowercases():
    domains = threat_feed.parse_blocklist(_fixture_text("blocklist_domains.txt"))
    assert domains == {"botnet-c2.example", "command-and-control.example"}


def test_parse_empty_input_yields_empty_set():
    assert threat_feed.parse_blocklist("") == set()
    assert threat_feed.parse_blocklist("# only comments\n! and abp comments\n") == set()


# ── URL validation ────────────────────────────────────────────────────────────


def test_validate_feed_url_rejects_http():
    with pytest.raises(ValueError):
        threat_feed.validate_feed_url("http://example.org/list.txt")


def test_validate_feed_url_rejects_file_scheme():
    with pytest.raises(ValueError):
        threat_feed.validate_feed_url("file:///etc/passwd")


def test_validate_feed_url_accepts_public_https():
    threat_feed.validate_feed_url("https://small.oisd.nl")


# ── serialization round-trip ─────────────────────────────────────────────────


def test_threat_feed_json_round_trip():
    feed = ThreatFeed(
        malware={"a.example"},
        trackers={"b.example"},
        botnets=set(),
        fetched_at="2026-07-15T00:00:00+00:00",
    )
    restored = ThreatFeed.from_json(feed.to_json())
    assert restored.malware == {"a.example"}
    assert restored.trackers == {"b.example"}
    assert restored.botnets == set()
    assert restored.fetched_at == "2026-07-15T00:00:00+00:00"
    assert restored.available is True


# ── get_feed cache behavior (fake Redis) ─────────────────────────────────────


def _fresh_feed_json() -> str:
    from datetime import UTC, datetime

    feed = ThreatFeed(malware={"cached.example"}, fetched_at=datetime.now(UTC).isoformat())
    return feed.to_json()


class _FakeProvider:
    def __init__(self, feed: ThreatFeed):
        self._feed = feed
        self.fetch_count = 0

    async def fetch(self) -> ThreatFeed:
        self.fetch_count += 1
        return self._feed


@pytest.mark.asyncio
async def test_get_feed_serves_fresh_cache_without_fetching():
    fake_redis = AsyncMock()
    fake_redis.get.return_value = _fresh_feed_json()
    provider = _FakeProvider(ThreatFeed(malware={"live.example"}))
    with patch("app.services.threat_feed.get_redis", return_value=fake_redis):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.malware == {"cached.example"}
    assert provider.fetch_count == 0


@pytest.mark.asyncio
async def test_get_feed_refetches_when_cache_expired():
    stale = ThreatFeed(malware={"old.example"}, fetched_at="2020-01-01T00:00:00+00:00")
    fake_redis = AsyncMock()
    fake_redis.get.return_value = stale.to_json()
    provider = _FakeProvider(
        ThreatFeed(malware={"live.example"}, fetched_at="2026-07-15T00:00:00+00:00")
    )
    with patch("app.services.threat_feed.get_redis", return_value=fake_redis):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.malware == {"live.example"}
    assert provider.fetch_count == 1
    fake_redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_get_feed_fetch_failure_serves_stale_cache():
    stale = ThreatFeed(malware={"old.example"}, fetched_at="2020-01-01T00:00:00+00:00")
    fake_redis = AsyncMock()
    fake_redis.get.return_value = stale.to_json()
    failed = ThreatFeed(available=False)
    provider = _FakeProvider(failed)
    with patch("app.services.threat_feed.get_redis", return_value=fake_redis):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.malware == {"old.example"}
    assert feed.stale is True
    assert feed.available is True


@pytest.mark.asyncio
async def test_get_feed_no_cache_and_fetch_failure_reports_unavailable():
    fake_redis = AsyncMock()
    fake_redis.get.return_value = None
    provider = _FakeProvider(ThreatFeed(available=False))
    with patch("app.services.threat_feed.get_redis", return_value=fake_redis):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.available is False


@pytest.mark.asyncio
async def test_get_feed_airgap_never_fetches():
    provider = _FakeProvider(ThreatFeed(malware={"live.example"}))
    with patch.object(threat_feed.settings, "airgap", True):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.available is False
    assert provider.fetch_count == 0


@pytest.mark.asyncio
async def test_get_feed_survives_redis_down():
    provider = _FakeProvider(
        ThreatFeed(malware={"live.example"}, fetched_at="2026-07-15T00:00:00+00:00")
    )
    with patch("app.services.threat_feed.get_redis", AsyncMock(return_value=None)):
        feed = await threat_feed.get_feed(refresh_hours=1, provider=provider)
    assert feed.malware == {"live.example"}


# ── provider download guard ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_skips_invalid_urls_and_stays_available_on_partial():
    provider = PublicBlocklistProvider(
        urls={"malware": ["http://insecure.example/list.txt"], "trackers": [], "botnets": []}
    )
    feed = await provider.fetch()
    # sole URL is invalid (non-HTTPS) — nothing fetched, feed unavailable
    assert feed.available is False
    assert feed.malware == set()


def test_default_feed_urls_are_https():
    for urls in threat_feed.default_feed_urls().values():
        for url in urls:
            assert url.startswith("https://")


def test_cached_payload_is_json_object():
    feed = ThreatFeed(malware={"a.example"})
    payload = json.loads(feed.to_json())
    assert set(payload) >= {"malware", "trackers", "botnets", "fetched_at", "source"}
