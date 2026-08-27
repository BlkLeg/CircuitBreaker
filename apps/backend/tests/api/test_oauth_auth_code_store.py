"""One-time OAuth auth codes had to survive the trip between uvicorn workers.

`docker/supervisord.mono.conf` starts the API as `uvicorn ... --workers 2`, so the
provider callback (`/auth/oauth/*/callback`) and the browser's follow-up
`/auth/exchange` are two separate connections that land on whichever worker the
kernel hands them to. The code→JWT map lived in a module-level dict, which is
per-process: when the two requests landed on different workers — about half the
time — the exchange found nothing and the sign-in died with
"Invalid or expired auth code" after the user had already authenticated.

These tests stand a fake Redis in for the one server both workers share, and
model the second worker the only way that matters here: its copy of
`_pending_auth_codes` is empty, because it is a different process.

The redeem side also has to stay single-use *across* workers, which is why the
fake below deliberately yields control inside its Redis calls. A GET followed by
a separate DELETE would let both workers observe the same token before either
delete lands; only the atomic server-side GETDEL closes that window.

Moving the store out of the process also moved a secret into a server that, in
the documented dev setup (`docker-compose.deps.yml`), listens on 0.0.0.0:6379
with no password. So the shape of what lands in Redis is asserted here too: the
key must be the hash of the code and the value must not be a readable JWT.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import time

import pytest
from cryptography.fernet import Fernet, InvalidToken


class SharedFakeRedis:
    """The one Redis server both uvicorn workers talk to.

    Every await point models a network round trip, so a caller that reads and
    deletes in two separate calls can be interleaved by another caller between
    them. `getdel` is the exception: it resolves and removes with no await in
    between, exactly as Redis executes GETDEL server-side.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float | None, str]] = {}
        self.ops: list[str] = []

    def _evict_if_expired(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is not None and entry[0] is not None and time.monotonic() >= entry[0]:
            del self._store[key]

    async def set(self, key: str, value: str, ex: float | None = None, nx: bool = False) -> bool:
        await asyncio.sleep(0)
        self.ops.append("set")
        self._evict_if_expired(key)
        if nx and key in self._store:
            return False
        self._store[key] = ((time.monotonic() + ex) if ex is not None else None, value)
        return True

    async def setex(self, key: str, ttl: float, value: str) -> bool:
        await asyncio.sleep(0)
        self.ops.append("setex")
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    async def get(self, key: str) -> str | None:
        await asyncio.sleep(0)
        self.ops.append("get")
        self._evict_if_expired(key)
        entry = self._store.get(key)
        return entry[1] if entry is not None else None

    async def delete(self, key: str) -> int:
        await asyncio.sleep(0)
        self.ops.append("delete")
        return 1 if self._store.pop(key, None) is not None else 0

    async def getdel(self, key: str) -> str | None:
        self.ops.append("getdel")
        self._evict_if_expired(key)
        entry = self._store.pop(key, None)
        await asyncio.sleep(0)
        return entry[1] if entry is not None else None


@pytest.fixture
def shared_redis(monkeypatch) -> SharedFakeRedis:
    """Point `app.core.redis.get_redis` at one fake server shared by both workers."""
    server = SharedFakeRedis()

    async def _get_redis():
        return server

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)
    return server


@pytest.fixture(autouse=True)
def _clean_pending_auth_codes():
    """The fallback map is module state; do not let one test seed the next."""
    from app.api import auth_oauth

    auth_oauth._pending_auth_codes.clear()
    yield
    auth_oauth._pending_auth_codes.clear()


def _become_the_other_worker() -> None:
    """Model worker B: a separate process, so its auth-code dict is empty."""
    from app.api import auth_oauth

    auth_oauth._pending_auth_codes.clear()


async def test_a_code_minted_on_one_worker_is_redeemed_on_the_other(client, shared_redis):
    """The bug, stated directly: the callback and the exchange are two connections."""
    from app.api.auth_oauth import _issue_auth_code

    code = await _issue_auth_code("jwt-from-the-callback-worker")
    _become_the_other_worker()

    resp = await client.get("/api/v1/auth/exchange", params={"code": code})

    assert resp.status_code == 200, resp.text
    assert resp.json()["token"] == "jwt-from-the-callback-worker"


async def test_a_shared_code_is_redeemable_exactly_once(client, shared_redis):
    """Moving the store off the process must not cost the one-time guarantee."""
    from app.api.auth_oauth import _issue_auth_code

    code = await _issue_auth_code("single-use-jwt")
    _become_the_other_worker()

    first = await client.get("/api/v1/auth/exchange", params={"code": code})
    second = await client.get("/api/v1/auth/exchange", params={"code": code})

    assert first.status_code == 200, first.text
    assert second.status_code == 400, "the code was redeemable twice"


async def test_two_workers_racing_on_the_same_code_cannot_both_win(shared_redis):
    """Both workers redeem at once; the delete must not be separable from the read.

    Calls the endpoint coroutine directly rather than through the ASGI client so
    the two redemptions are genuinely interleaved on one event loop.
    """
    from app.api.auth_oauth import _issue_auth_code, exchange_auth_code

    code = await _issue_auth_code("contested-jwt")
    _become_the_other_worker()

    async def _redeem():
        try:
            return await inspect.unwrap(exchange_auth_code)(None, None, code)
        except Exception as exc:  # HTTPException(400) is the losing worker
            return exc

    results = await asyncio.gather(_redeem(), _redeem())
    winners = [r for r in results if isinstance(r, dict)]

    assert len(winners) == 1, f"expected exactly one redemption to win, got {results!r}"
    assert winners[0]["token"] == "contested-jwt"
    assert "get" not in shared_redis.ops, (
        "the code was read with a non-deleting GET — a second worker can slip in "
        "before the DELETE and redeem the same code"
    )


async def test_with_redis_down_the_code_still_works_within_one_worker(client, monkeypatch):
    """An outage degrades to this worker, and recovery must clear what it stranded.

    Two things are pinned here, and the first half alone pins neither: a test
    that only ever sees Redis down cannot tell the shared store from the
    per-process dict it replaced, because with Redis down they behave
    identically. So the test rides the outage *through* to recovery.

    - While Redis is down the sign-in still completes on this worker and the
      code is still single-use (`core/redis.py`'s contract: degraded, not
      broken). That guards against over-fixing the fallback away.
    - Once Redis is back, a freshly minted code crosses the worker boundary
      again, and the entries the outage deposited in process memory are reaped
      on the next mint. Each of those entries holds a full session JWT valid
      for cfg.session_timeout_hours; when the prune sat after the Redis write
      it stopped running the moment Redis was healthy, and they were held for
      the life of the worker.
    """
    from app.api import auth_oauth
    from app.api.auth_oauth import _issue_auth_code

    server = SharedFakeRedis()
    reachable = False

    async def _get_redis():
        return server if reachable else None

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    degraded = await _issue_auth_code("degraded-jwt")
    stranded = await _issue_auth_code("stranded-jwt")  # minted, never redeemed

    first = await client.get("/api/v1/auth/exchange", params={"code": degraded})
    second = await client.get("/api/v1/auth/exchange", params={"code": degraded})

    assert first.status_code == 200, first.text
    assert first.json()["token"] == "degraded-jwt"
    assert second.status_code == 400, "the in-process fallback lost its one-time guarantee"

    # The stranded code's 60 s window closes while Redis is still unreachable.
    held_token, _ = auth_oauth._pending_auth_codes[stranded]
    auth_oauth._pending_auth_codes[stranded] = (held_token, time.monotonic() - 1.0)

    reachable = True
    recovered = await _issue_auth_code("recovered-jwt")

    assert stranded not in auth_oauth._pending_auth_codes, (
        "an expired code stranded in process memory by the outage was never reaped — "
        "its session JWT is held for the life of the worker"
    )

    _become_the_other_worker()
    resp = await client.get("/api/v1/auth/exchange", params={"code": recovered})

    assert resp.status_code == 200, resp.text
    assert resp.json()["token"] == "recovered-jwt"


async def test_redis_holds_neither_the_code_nor_a_readable_token(shared_redis):
    """A reader of Redis must get nothing usable out of a pending auth code.

    The dev compose file publishes redis on 0.0.0.0:6379 with no requirepass,
    so `SCAN cb:oauth:authcode:*` is within reach of anything on the host. It
    must not turn up a live redeemable code (key = hash, per
    services/agent_enrollment.py) nor the session JWT itself (value sealed
    under a key derived from the code, which is never written down).
    """
    from app.api.auth_oauth import _AUTH_CODE_KEY_PREFIX, _issue_auth_code

    jwt_value = "jwt.a.redis.reader.must.not.get"
    code = await _issue_auth_code(jwt_value)

    (key,) = list(shared_redis._store)
    assert key.startswith(_AUTH_CODE_KEY_PREFIX)
    assert code not in key, (
        "the auth code is its own Redis key — a SCAN hands out a live redeemable code"
    )

    stored = shared_redis._store[key][1]
    stored = stored.decode() if isinstance(stored, bytes) else str(stored)
    assert jwt_value not in stored, "the session JWT is sitting in Redis in the clear"

    # ...and the key name must not be the thing that unseals the value, which is
    # what happens if the lookup hash and the cipher key stop being
    # domain-separated.
    key_name_digest = bytes.fromhex(key[len(_AUTH_CODE_KEY_PREFIX) :])
    from_key_name = Fernet(base64.urlsafe_b64encode(key_name_digest))
    with pytest.raises(InvalidToken):
        from_key_name.decrypt(stored.encode())

    # Sanity: the code itself still opens it, so this is secrecy, not breakage.
    seal = hashlib.sha256(b"cb-oauth-authcode-seal-v1|" + code.encode()).digest()
    opened = Fernet(base64.urlsafe_b64encode(seal)).decrypt(stored.encode()).decode()
    assert opened == jwt_value
