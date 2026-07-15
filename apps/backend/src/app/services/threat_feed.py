"""Pluggable threat-intel feed: public blocklists, Redis-cached, airgap-aware.

Feed data powers the ``dns_filtering_absent`` network check; device badges stay
scan-derived (spec decision). A keyed Windscribe/ControlD provider can be added
later by implementing ``FeedProvider`` — consumers only see ``ThreatFeed``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse

import httpx
import redis

from app.core.config import settings
from app.core.constants import (
    FEED_CACHE_KEY,
    FEED_FETCH_TIMEOUT_S,
    FEED_MAX_RESPONSE_BYTES,
    FEED_SOURCE_PUBLIC_BLOCKLISTS,
)
from app.core.redis import get_redis
from app.core.url_validation import reject_ssrf_url
from app.services.threat_feed_parse import parse_blocklist

logger = logging.getLogger(__name__)

__all__ = [
    "FeedProvider",
    "PublicBlocklistProvider",
    "ThreatFeed",
    "default_feed_urls",
    "get_feed",
    "parse_blocklist",
    "validate_feed_url",
]

_FEED_CATEGORIES = ("malware", "trackers", "botnets")


def default_feed_urls() -> dict[str, list[str]]:
    """Default public blocklists (all HTTPS, no API key). Overridable via config.

    Note: the spec's Hagezi TIF list (39 MB) exceeds the response-size cap and its
    mini variant is no longer published; ControlD's free list has no keyless URL.
    abuse.ch URLhaus/ThreatFox are the equivalent compact threat feeds.
    """
    return {
        "malware": ["https://urlhaus.abuse.ch/downloads/hostfile/"],
        "trackers": ["https://small.oisd.nl"],
        "botnets": ["https://threatfox.abuse.ch/downloads/hostfile/"],
    }


@dataclass
class ThreatFeed:
    malware: set[str] = field(default_factory=set)
    trackers: set[str] = field(default_factory=set)
    botnets: set[str] = field(default_factory=set)
    fetched_at: str | None = None
    source: str = FEED_SOURCE_PUBLIC_BLOCKLISTS
    stale: bool = False
    available: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {
                "malware": sorted(self.malware),
                "trackers": sorted(self.trackers),
                "botnets": sorted(self.botnets),
                "fetched_at": self.fetched_at,
                "source": self.source,
                "available": self.available,
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> ThreatFeed:
        payload = json.loads(raw)
        return cls(
            malware=set(payload.get("malware", [])),
            trackers=set(payload.get("trackers", [])),
            botnets=set(payload.get("botnets", [])),
            fetched_at=payload.get("fetched_at"),
            source=payload.get("source", FEED_SOURCE_PUBLIC_BLOCKLISTS),
            available=payload.get("available", True),
        )


class FeedProvider(Protocol):
    async def fetch(self) -> ThreatFeed: ...


def validate_feed_url(url: str) -> None:
    """Feed URLs must be HTTPS and pass the SSRF guard (no private/loopback)."""
    scheme = (urlparse(url).scheme or "").lower()
    if scheme != "https":
        raise ValueError(f"Feed URL must use HTTPS, got scheme '{scheme}'")
    reject_ssrf_url(url)


class PublicBlocklistProvider:
    """Downloads configured blocklist URLs and parses them into category sets."""

    def __init__(self, urls: dict[str, list[str]] | None = None) -> None:
        self.urls = urls if urls is not None else default_feed_urls()

    async def fetch(self) -> ThreatFeed:
        feed = ThreatFeed(fetched_at=datetime.now(UTC).isoformat())
        fetched_any = False
        async with httpx.AsyncClient(timeout=FEED_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            for category in _FEED_CATEGORIES:
                for url in self.urls.get(category, []):
                    domains = await self._fetch_one(client, url)
                    if domains is None:
                        continue
                    fetched_any = True
                    getattr(feed, category).update(domains)
        feed.available = fetched_any
        return feed

    async def _fetch_one(self, client: httpx.AsyncClient, url: str) -> set[str] | None:
        try:
            validate_feed_url(url)
            return parse_blocklist(await self._download_capped(client, url))
        except ValueError as exc:
            logger.warning("[threat_feed] skipping feed URL %s: %s", url, exc)
            return None
        except httpx.HTTPError as exc:
            logger.warning("[threat_feed] fetch failed for %s: %s", url, exc)
            return None

    @staticmethod
    async def _download_capped(client: httpx.AsyncClient, url: str) -> str:
        chunks: list[bytes] = []
        total_bytes = 0
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                total_bytes += len(chunk)
                if total_bytes > FEED_MAX_RESPONSE_BYTES:
                    raise ValueError(f"response exceeds {FEED_MAX_RESPONSE_BYTES} byte cap")
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="ignore")


def _is_fresh(feed: ThreatFeed, refresh_hours: int) -> bool:
    if not feed.fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(feed.fetched_at)
    except ValueError:
        return False
    return datetime.now(UTC) - fetched < timedelta(hours=max(1, refresh_hours))


async def _load_cached_feed() -> ThreatFeed | None:
    try:
        client = await get_redis()
        if client is None:
            return None
        raw = await client.get(FEED_CACHE_KEY)
        return ThreatFeed.from_json(raw) if raw else None
    except redis.RedisError as exc:
        logger.warning("[threat_feed] cache read failed: %s", exc)
        return None
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("[threat_feed] corrupt feed cache, ignoring: %s", exc)
        return None


async def _store_feed(feed: ThreatFeed) -> None:
    try:
        client = await get_redis()
        if client is not None:
            await client.set(FEED_CACHE_KEY, feed.to_json())
    except redis.RedisError as exc:
        logger.warning("[threat_feed] cache write failed: %s", exc)


async def get_feed(refresh_hours: int, provider: FeedProvider | None = None) -> ThreatFeed:
    """Return the threat feed: cached when fresh, refetched when stale.

    Fetch failure serves the last cached feed flagged ``stale``; with no cache it
    reports ``available=False``. Airgap mode never attempts an outbound fetch.
    """
    if settings.airgap:
        return ThreatFeed(available=False, source="airgap")

    cached = await _load_cached_feed()
    if cached is not None and cached.available and _is_fresh(cached, refresh_hours):
        return cached

    active_provider = provider if provider is not None else PublicBlocklistProvider()
    fresh = await active_provider.fetch()
    if fresh.available:
        await _store_feed(fresh)
        return fresh

    if cached is not None and cached.available:
        cached.stale = True
        return cached
    return fresh
