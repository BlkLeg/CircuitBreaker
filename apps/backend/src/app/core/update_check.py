"""Non-blocking update check against GitHub Releases API."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from app.core import version as _version

logger = logging.getLogger("circuitbreaker.update_check")

GITHUB_RELEASES_URL = "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases/latest"
CHECK_TIMEOUT = 5  # seconds


@dataclass(frozen=True)
class UpdateVerdict:
    """status is 'ok' or 'unknown_version'; available is None when newest."""

    status: str
    channel: str
    available: str | None


def channels_from_releases(releases: list[dict]) -> dict[str, list[str]]:
    """Normalise a GitHub /releases list into per-channel version lists.

    Drafts are never installable. The `prerelease` channel holds everything,
    because a candidate install is offered the newest release of any kind
    (spec D2); `stable` holds only release versions.
    """
    versions: list[str] = []
    for entry in releases:
        if entry.get("draft"):
            continue
        tag = str(entry.get("tag_name") or "").strip().lstrip("vV")
        if tag:
            versions.append(tag)
    return {
        "stable": [v for v in versions if not _version.is_prerelease(v)],
        "prerelease": list(versions),
    }


def select_update(
    current: str,
    channels: dict[str, list[str]],
    withdrawn: Iterable[str] = (),
) -> UpdateVerdict:
    """Newest release in the caller's own channel. Pure — no I/O.

    A `current` that does not appear in its channel is a local or withdrawn
    build. There is no honest comparison to make, so nothing is offered
    (spec section 3.3) — guessing here is how someone gets pushed sideways
    onto a build that is not an upgrade.
    """
    channel = "prerelease" if _version.is_prerelease(current) else "stable"
    blocked = set(withdrawn)
    entries = [v for v in channels.get(channel, ()) if v not in blocked]

    if current not in entries:
        return UpdateVerdict(status="unknown_version", channel=channel, available=None)

    ranked = [v for v in entries if _version.parse(v) is not None]
    newest = max(ranked, key=_version.parse)
    available = newest if _version.is_newer(newest, current) else None
    return UpdateVerdict(status="ok", channel=channel, available=available)


async def check_for_update(current_version: str) -> str | None:
    """Return latest version string if newer than current, else None.

    Returns None on any error (network, parse, timeout) — never blocks startup.
    """
    try:
        import httpx
    except ImportError:
        return None

    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            latest = str(data.get("tag_name", ""))
            if latest and _version.is_newer(latest, current_version):
                return latest
    except Exception:
        # Never let update check break the app
        return None
    return None


async def log_update_notice(current_version: str) -> None:
    """Log a notice if a newer version is available."""
    latest = await check_for_update(current_version)
    if latest:
        logger.info(
            "A newer version of Circuit Breaker is available: %s (current: %s). "
            "See https://github.com/BlkLeg/CircuitBreaker/releases/%s",
            latest,
            current_version,
            latest,
        )
