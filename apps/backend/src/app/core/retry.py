"""Async retry helpers for outbound integration calls (Proxmox, ILO, etc.)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

_logger = logging.getLogger(__name__)

# Default: 3 attempts, backoff 1s, 2s (exponential).
INTEGRATION_RETRY_ATTEMPTS = 3
INTEGRATION_RETRY_BASE_DELAY_S = 1.0


async def run_sync_with_retry[T](
    sync_fn: Callable[[], T],
    *,
    max_attempts: int = INTEGRATION_RETRY_ATTEMPTS,
    base_delay_s: float = INTEGRATION_RETRY_BASE_DELAY_S,
    log_context: str = "integration",
) -> T:
    """Run a synchronous callable in a thread and retry on failure with exponential backoff.

    Use for Proxmox/ILO API calls so transient network or server errors do not surface as hard failures.
    """
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await asyncio.to_thread(sync_fn)
        except Exception as e:
            last = e
            if attempt < max_attempts - 1:
                delay = base_delay_s * (2**attempt)
                _logger.debug(
                    "%s attempt %s/%s failed, retrying in %.1fs: %s",
                    log_context,
                    attempt + 1,
                    max_attempts,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
    raise last  # type: ignore[misc]
