"""Pool exhaustion must not be mistaken for a dead Redis server.

Every pub/sub subscriber (each telemetry, monitor, discovery and agent
WebSocket) holds a connection out of the *same* pool the command path draws
from, for the whole life of its socket.  Once enough of them are up, the next
``PING`` on the command path gets ``MaxConnectionsError`` instead of a reply.

The dangerous part is not the failed PING — it is what the client used to do
about it: treat any ping failure as a lost server and call ``aclose()``, which
in redis-py calls ``pool.disconnect()`` with ``inuse_connections=True`` and
tears down every live subscriber socket along with it.  A local resource
shortage would take out the entire real-time layer.
"""

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import MaxConnectionsError

from app.core import redis as redis_mod


class _FakeRedis:
    """Stands in for the cached client; records whether it was torn down."""

    def __init__(self, ping_error: Exception | None) -> None:
        self._ping_error = ping_error
        self.aclose_calls = 0

    async def ping(self) -> bool:
        if self._ping_error is not None:
            raise self._ping_error
        return True

    async def aclose(self) -> None:
        self.aclose_calls += 1


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Restore the module singleton so tests never leak a fake into the app."""
    saved_client = redis_mod._redis
    saved_attempt = redis_mod._last_reconnect_attempt
    yield
    redis_mod._redis = saved_client
    redis_mod._last_reconnect_attempt = saved_attempt


async def test_pool_exhaustion_degrades_the_call_without_disconnecting_subscribers(monkeypatch):
    client = _FakeRedis(MaxConnectionsError("Too many connections"))
    redis_mod._redis = client
    redis_mod._last_reconnect_attempt = 0.0

    # A real Redis may well be listening on the developer's machine; pin the
    # reconnect path shut so this asserts on the branch taken, not the host.
    reconnects: list[int] = []

    async def _no_reconnect(connect_timeout: int = 5):
        reconnects.append(connect_timeout)
        return None

    monkeypatch.setattr(redis_mod, "_try_connect", _no_reconnect)

    result = await redis_mod.get_redis()

    assert client.aclose_calls == 0, (
        "aclose() disconnects in-use connections — it would sever every live "
        "pub/sub socket over a shortage that resolves on its own"
    )
    assert redis_mod._redis is client, (
        "the client is healthy; dropping it forces a needless reconnect cycle"
    )
    assert not reconnects, "an exhausted pool is not a reason to redial the server"
    assert result is None, "an exhausted pool has no connection to hand this caller"


async def test_a_genuinely_dead_server_still_drops_and_reconnects(monkeypatch):
    """The exhaustion branch must not swallow real connection loss."""
    client = _FakeRedis(RedisConnectionError("Connection closed by server"))
    redis_mod._redis = client
    redis_mod._last_reconnect_attempt = 0.0

    async def _no_reconnect(connect_timeout: int = 5):
        return None

    monkeypatch.setattr(redis_mod, "_try_connect", _no_reconnect)

    result = await redis_mod.get_redis()

    assert result is None
    assert client.aclose_calls == 1
    assert redis_mod._redis is None


def test_the_pool_is_sized_for_the_shipped_subscriber_caps():
    """20 connections cannot cover 100 telemetry + 100 monitor subscribers."""
    assert redis_mod._MAX_CONNECTIONS >= 250
