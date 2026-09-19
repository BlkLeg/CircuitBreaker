"""A bounded in-process memo for identity assessment outcomes.

Matching an identity means scanning the applicability table, so the same answer
must not be recomputed for every page load. The key carries the feed generation
and the feed's state, which is what makes invalidation automatic: a completed
sync changes the generation, and a generation ageing past the freshness policy
changes the state.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from app.schemas.cve import AssessmentResult

CACHE_MAX_ENTRIES = 512

_lock = threading.Lock()
_entries: OrderedDict[tuple[Any, ...], AssessmentResult] = OrderedDict()


def identity_cache_key(
    generation: str,
    feed_state: str,
    key: tuple[str | None, str | None, str | None, str | None],
) -> tuple[Any, ...]:
    """The key an outcome is stored under."""
    return (generation, feed_state, *key)


def cached_outcome(cache_key: tuple[Any, ...]) -> AssessmentResult | None:
    """The stored outcome, or None. Marks the entry as most recently used."""
    with _lock:
        result = _entries.get(cache_key)
        if result is not None:
            _entries.move_to_end(cache_key)
        return result


def remember_outcome(cache_key: tuple[Any, ...], result: AssessmentResult) -> None:
    """Store an outcome, evicting the least recently used entry when full."""
    with _lock:
        _entries[cache_key] = result
        _entries.move_to_end(cache_key)
        while len(_entries) > CACHE_MAX_ENTRIES:
            _entries.popitem(last=False)


def clear_identity_cache() -> None:
    """Drop every entry. Used by tests and by an operator-triggered feed sync."""
    with _lock:
        _entries.clear()
