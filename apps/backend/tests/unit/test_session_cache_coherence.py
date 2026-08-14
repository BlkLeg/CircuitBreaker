"""The session-validation cache must not outlive a revocation in another worker.

The app ships behind `uvicorn --workers 2`. Each worker held its own cache with
a 10 s TTL and cleared only its own entry on logout, so a session revoked by
worker A kept working on worker B until B's copy aged out.
"""

from __future__ import annotations

import pytest

from app.core import security


class _FakeRedis:
    """Minimal stand-in for the shared store: MGET, SETEX, INCR."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.down = False

    def _check(self):
        if self.down:
            raise ConnectionError("redis is down")

    def mget(self, *keys):
        self._check()
        return [self.store.get(k) for k in keys]

    def setex(self, key, _ttl, value):
        self._check()
        self.store[key] = str(value)

    def incr(self, key):
        self._check()
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])


@pytest.fixture
def shared(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.redis.get_sync_redis", lambda: fake)
    monkeypatch.setattr("app.core.redis.reset_sync_redis", lambda: None)
    monkeypatch.setattr(security, "_session_cache", {})
    monkeypatch.setattr(security, "_local_flush_epoch", None)
    return fake


TOKEN = "worker-coherence-token"


def _hash(token: str) -> str:
    return security._hash_token_for_cache(token)


def test_cached_entry_is_served_while_the_session_is_untouched(shared):
    security._session_cache_set(_hash(TOKEN), 7, ("read:*",))
    # First read adopts the shared flush epoch (None), second is a plain hit.
    security._session_cache_get(_hash(TOKEN))
    security._session_cache_set(_hash(TOKEN), 7, ("read:*",))
    assert security._session_cache_get(_hash(TOKEN)) == (7, ("read:*",))


def test_revocation_in_another_worker_drops_this_workers_cached_entry(shared):
    security._session_cache_set(_hash(TOKEN), 7, ("read:*",))
    security._session_cache_get(_hash(TOKEN))  # settle the epoch
    security._session_cache_set(_hash(TOKEN), 7, ("read:*",))

    # Another worker revokes: it writes the marker, this process never saw the call.
    shared.store[f"{security._REVOKED_KEY_PREFIX}{_hash(TOKEN)}"] = "1"

    assert security._session_cache_get(_hash(TOKEN)) is None
    assert _hash(TOKEN) not in security._session_cache, "stale entry should be evicted"


def test_bulk_revocation_elsewhere_flushes_this_workers_whole_cache(shared):
    security._session_cache_set(_hash(TOKEN), 7, None)
    security._session_cache_get(_hash(TOKEN))  # settle the epoch
    security._session_cache_set(_hash(TOKEN), 7, None)
    security._session_cache_set(_hash("other"), 8, None)

    shared.incr(security._FLUSH_EPOCH_KEY)  # e.g. a password change on the other worker

    assert security._session_cache_get(_hash(TOKEN)) is None
    assert security._session_cache == {}


def test_cache_is_bypassed_entirely_when_the_shared_store_is_unreachable(shared):
    """Degrade to full database validation — slow, not stale."""
    security._session_cache_set(_hash(TOKEN), 7, None)
    shared.down = True
    assert security._session_cache_get(_hash(TOKEN)) is None


def test_invalidation_publishes_a_marker_the_other_workers_can_see(shared):
    security.invalidate_session_cache(TOKEN)
    assert f"{security._REVOKED_KEY_PREFIX}{_hash(TOKEN)}" in shared.store


def test_bulk_invalidation_bumps_the_shared_epoch(shared):
    security.invalidate_session_cache(None)
    assert shared.store.get(security._FLUSH_EPOCH_KEY) == "1"


def test_invalidation_still_clears_locally_when_the_shared_store_is_down(shared):
    security._session_cache_set(_hash(TOKEN), 7, None)
    shared.down = True
    security.invalidate_session_cache(TOKEN)  # must not raise
    assert _hash(TOKEN) not in security._session_cache
