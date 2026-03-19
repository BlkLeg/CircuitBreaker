"""Non-blocking update check against GitHub Releases API."""

from __future__ import annotations

import logging

logger = logging.getLogger("circuitbreaker.update_check")

GITHUB_RELEASES_URL = "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases/latest"
CHECK_TIMEOUT = 5  # seconds


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3-beta' into a comparable tuple."""
    clean = v.lstrip("v").split("-")[0]
    try:
        return tuple(int(x) for x in clean.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


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
            if latest and _parse_version(latest) > _parse_version(current_version):
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
