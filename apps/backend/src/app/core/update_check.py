"""Non-blocking release check.

Two defects made this dead code for the whole 1.0.0-rc window. It asked
`/releases/latest`, which resolves through GitHub's "Latest release" badge and
names the newest *stable* release -- `v0.3.4` throughout the rc window. And it
compared `v.lstrip("v").split("-")[0]`, so `1.0.0-rc.2` and `1.0.0-rc.4` were
both `(1, 0, 0)` and no candidate install could ever be told to upgrade.

The cache is in-memory by design: hardening section 8 runs the container
`read_only: true` with only `/data` writable.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx

from app.core import version as _version
from app.core.config import settings
from app.core.install_method import detect_install_method, upgrade_command
from app.core.url_validation import outbound_async_client

logger = logging.getLogger("circuitbreaker.update_check")

GITHUB_RELEASES_URL = "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases"
CHECK_TIMEOUT = 5  # seconds
CHECK_INTERVAL_S = 24 * 60 * 60
JITTER_S = 30 * 60
# GitHub defaults /releases to 30 per page. Once the repo publishes more
# than 30 releases, an install older than the newest 30 falls off the list,
# `current not in entries` holds, and select_update returns unknown_version
# -- offering nothing, silently. That is the reported field bug arriving
# through a different door. 100 is the API maximum.
RELEASES_PER_PAGE = 100


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

    `current` is v-stripped before the membership test. `channels_from_releases`
    already strips the tag's `v`, and APP_VERSION is an operator-settable env
    var, so a `v1.0.0-rc.2` value used to miss every entry and yield
    `unknown_version` — silently offering nothing, which is the exact failure
    this module exists to end.
    """
    current = _version.clean(current)
    channel = "prerelease" if _version.is_prerelease(current) else "stable"
    blocked = {_version.clean(v) for v in withdrawn}
    entries = [_version.clean(v) for v in channels.get(channel, ())]
    entries = [v for v in entries if v not in blocked]

    if current not in entries:
        return UpdateVerdict(status="unknown_version", channel=channel, available=None)

    ranked = [v for v in entries if _version.parse(v) is not None]
    if not ranked:
        # `current` matched an entry no version parser accepts (e.g. a channel
        # of {"prerelease": ["nightly"]}). max() over an empty list raises
        # ValueError, which refresh() would swallow into status "unreachable" —
        # a lie, because the network was fine.
        return UpdateVerdict(status="unknown_version", channel=channel, available=None)
    newest = max(ranked, key=_version.parse)
    available = newest if _version.is_newer(newest, current) else None
    return UpdateVerdict(status="ok", channel=channel, available=available)


@dataclass(frozen=True)
class UpdateState:
    status: str = "never_checked"
    current: str = ""
    available: str | None = None
    channel: str = ""
    checked_at: str | None = None
    etag: str | None = None
    # The status the cached etag was earned under. A 304 says "the release list
    # has not changed", so the verdict that produced this etag is still the
    # right answer -- including its status. Without this, one transient failure
    # between a 200 and a 304 pinned status="unreachable" forever, because
    # GitHub keeps answering 304 until a new release is published, which can be
    # months. The Settings panel then read "Could not reach the release source"
    # immediately after a successful check.
    etag_status: str = ""


_state = UpdateState()


def current_state() -> UpdateState:
    return _state


def reset_cache() -> None:
    """Test seam."""
    global _state
    _state = UpdateState()


def _transport() -> httpx.AsyncBaseTransport | None:
    """Test seam; None means httpx's default transport."""
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def refresh(*, airgap_override: bool = False) -> UpdateState:
    """Refresh the cached verdict. Never raises, never blocks a caller.

    `airgap_override` carries the DB-backed `AppSettings.airgap_mode` flag,
    which the loop reads for us -- see `_db_airgap_enabled`. It is a keyword so
    the env-only short-circuit keeps its existing shape.
    """
    global _state
    current = settings.app_version

    if airgap_override or settings.airgap:
        _state = replace(_state, status="airgap", current=current, available=None)
        return _state
    if not settings.update_check:
        _state = replace(_state, status="disabled", current=current, available=None)
        return _state

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"circuit-breaker/{current}",
    }
    if _state.etag:
        headers["If-None-Match"] = _state.etag

    transport = _transport()
    kwargs: dict = {"timeout": CHECK_TIMEOUT, "headers": headers}
    if transport is not None:
        kwargs["transport"] = transport

    try:
        # outbound_async_client applies the configured egress proxy and pins
        # trust_env=False with it, the same way threat_feed, auth_oauth,
        # notifications and notification_worker reach the network. Hand-rolling
        # the proxy wiring here left this the one outbound caller that still
        # honoured an ambient HTTPS_PROXY.
        async with outbound_async_client(**kwargs) as client:
            resp = await client.get(GITHUB_RELEASES_URL, params={"per_page": RELEASES_PER_PAGE})
            if resp.status_code == 304:
                # Restore the status the etag was earned under; see UpdateState.
                _state = replace(
                    _state,
                    status=_state.etag_status or _state.status,
                    checked_at=_now(),
                )
                return _state
            if resp.status_code != 200:
                raise httpx.HTTPError(f"status {resp.status_code}")
            payload = resp.json()
            if not isinstance(payload, list):
                raise httpx.HTTPError("release list was not a list")
            verdict = select_update(current, channels_from_releases(payload))
            _state = UpdateState(
                status=verdict.status,
                current=current,
                available=verdict.available,
                channel=verdict.channel,
                checked_at=_now(),
                etag=resp.headers.get("ETag") or _state.etag,
                etag_status=verdict.status,
            )
    except Exception as exc:  # network, JSON, schema — all the same to a caller
        logger.debug("Update check failed: %s", exc)
        _state = replace(_state, status="unreachable", current=current, checked_at=_now())
    return _state


def _db_airgap_enabled() -> bool:
    """The DB-backed air-gap flag (`AppSettings.airgap_mode`), best effort.

    `settings.airgap` is the env switch; operators can also flip air-gap mode in
    the UI, which writes `AppSettings.airgap_mode` -- the pair
    `discovery_service.py` passes to `validate_scan_target` as
    (`airgap_env`, `airgap_db`). Honouring only the env half meant an operator
    who air-gapped from the UI still had a daily call leave the box.

    Read-only on purpose: `db.get` rather than `get_or_create_settings`, so a
    background loop never writes a settings row. Any failure returns False,
    which only means the check runs exactly as it does today -- reading this
    flag can only ever reduce egress, and it can never affect scan behaviour.
    """
    try:
        from app.db.models import AppSettings  # noqa: PLC0415
        from app.db.session import get_session_context  # noqa: PLC0415

        with get_session_context() as db:
            row = db.get(AppSettings, 1)
            return bool(getattr(row, "airgap_mode", False)) if row is not None else False
    except Exception as exc:  # DB down, not migrated yet, no table
        logger.debug("Could not read airgap_mode: %s", exc)
        return False


async def run_update_check_loop() -> None:
    """Check now, then once a day with jitter until cancelled."""
    while True:
        # to_thread because get_session_context is synchronous SQLAlchemy and
        # this coroutine shares the request event loop.
        db_airgap = await asyncio.to_thread(_db_airgap_enabled)
        state = await refresh(airgap_override=db_airgap)
        if state.available:
            logger.info(
                "A newer version of Circuit Breaker is available: %s (current: %s). To upgrade: %s",
                state.available,
                state.current,
                upgrade_command(detect_install_method(), state.available),
            )
        try:
            await asyncio.sleep(CHECK_INTERVAL_S + random.uniform(0, JITTER_S))
        except asyncio.CancelledError:
            raise
