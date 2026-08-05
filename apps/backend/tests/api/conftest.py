"""Fixtures scoped to tests/api/ only — kept out of the top-level conftest.py
so their cost (a Redis connection attempt per test) isn't paid by every test
in the suite, including modules with nothing to do with WS agent endpoints.
"""

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def reset_agent_ws_redis_counters():
    """Clear Task 21's Redis-backed WS attempt / pairing-miss counters before
    every test under tests/api/.

    Whenever this dev/test host happens to have a real Redis reachable at
    CB_REDIS_URL's default (rather than every test explicitly mocking
    `get_redis`), Starlette's `TestClient` reports the same fixed client
    host for every WS connection it makes. Without this reset, the fixed
    60s/15min windows behind `check_and_record_ws_attempt` and
    `is_pairing_locked_out` would accumulate across unrelated tests in the
    same run and eventually start tripping the very limits under test —
    not because any single test is doing anything wrong, but purely from
    running the suite. Scoped to just the key prefixes Task 21 introduced,
    not a blanket FLUSHDB, so it can't clobber unrelated state some other
    test or a manually-running dev instance may have left in the same
    Redis. Tests that monkeypatch `get_redis` to their own fake are
    unaffected either way, since this never touches whatever they inject.

    Deliberately opens its own short-lived connection rather than routing
    through `app.core.redis.get_redis` (the app's cached singleton): the
    `ws_client` TestClient fixture runs the real app in a background
    anyio-portal thread with its own event loop, so reusing the singleton
    from *this* fixture's (different) pytest-asyncio loop risks binding it
    to whichever loop touches it first and having every other-loop call
    fail with "Future attached to a different loop" — caught by a bare
    `except Exception` and silently swallowed, which would leave stale
    counters in place with no visible error at all.

    Directory-scoped (this file, not the top-level conftest.py) rather than
    suite-wide autouse: in an environment where Redis genuinely isn't
    running, every test still pays one quick connect-refused attempt, so
    this keeps that cost confined to the one directory that actually needs
    it instead of every test module in the whole backend suite.
    """
    import os

    import redis.asyncio as aioredis

    url = os.environ.get("CB_REDIS_URL", "redis://localhost:6379/0")
    client = None
    try:
        client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        await client.ping()
        keys = [k async for k in client.scan_iter(match="agent_ws_attempt:*")]
        keys += [k async for k in client.scan_iter(match="agent_pairing_miss:*")]
        if keys:
            await client.delete(*keys)
    except Exception:
        pass  # Non-fatal — real Redis is incidental to these tests, not required
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
    yield
