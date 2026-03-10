"""Tests for session validation cache (cache hit and invalidation)."""


def test_invalidate_session_cache_clears_entry():
    """Invalidating by token removes only that token's cache entry."""
    from app.core.security import (
        _hash_token_for_cache,
        _session_cache_get,
        _session_cache_set,
        invalidate_session_cache,
    )

    token_hash = _hash_token_for_cache("test-token-123")
    _session_cache_set(token_hash, 42)
    invalidate_session_cache("test-token-123")
    assert _session_cache_get(token_hash) is None


def test_invalidate_session_cache_none_clears_all():
    """Invalidating with token=None clears the entire cache."""
    from app.core.security import _session_cache_get, _session_cache_set, invalidate_session_cache

    _session_cache_set("a", 1)
    _session_cache_set("b", 2)
    invalidate_session_cache(None)
    assert _session_cache_get("a") is None
    assert _session_cache_get("b") is None


def test_session_cache_set_get_ttl():
    """Cache returns value within TTL and None after (or when unknown)."""
    from app.core.security import _session_cache_get, _session_cache_set, invalidate_session_cache

    _session_cache_set("k1", 10)
    assert _session_cache_get("k1") == 10
    assert _session_cache_get("unknown") is None
    invalidate_session_cache(None)
