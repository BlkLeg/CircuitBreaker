"""Two concurrent polls of one iLO host must never drive one requests.Session.

R8, a regression introduced by the B07 fix (745a99b9). ``poll_hardware`` keeps a
process-wide cache of ``ILOClient`` instances keyed by (profile, host, username)
so repeated polls of the same BMC reuse one connection pool. Each client owns a
``requests.Session``, which is explicitly *not* thread-safe.

Before B07 the manual poll called ``poll_hardware`` inline from an ``async def``
endpoint, so it only ever ran on the event loop thread and two polls of one host
could not overlap. B07 moved it to ``asyncio.to_thread``. Any admin can now fire
N concurrent "poll now" requests at the same hardware row and put N worker
threads inside one cached Session at once — interleaved header mutation, cookie
jar writes and redirect handling on shared state, which surfaces as garbled
Redfish responses or a wedged connection pool rather than as a clean traceback.

These tests assert the invariant directly: whatever the cache does, no client
instance may have more than one thread inside ``poll()`` at a time. That
includes the paths through cache *eviction*: the first attempt at this fix kept
the per-key locks in a dict parallel to the client cache, and the two drifted
apart the moment the eviction branch fired, which put the invariant back on the
floor while the code claimed it held.
"""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

import app.integrations.dispatcher as dispatcher

# Set by a test before it fires its concurrent threads. While it is None the
# stub client returns immediately, which is what the cache-warming call needs.
_GATE: dict[str, threading.Barrier | threading.Event | None] = {"barrier": None, "hold": None}

# Per-host (entered, release) pair that parks a client *constructor*. Building a
# client is the window in which a key is cached-but-not-yet-usable, and it is
# the window the eviction regression lives in, so a test needs to hold a thread
# open inside it.
_BUILD_GATE: dict[str, tuple[threading.Event, threading.Event]] = {}

# Hosts whose constructor must raise, and hosts whose close() must raise. Both
# are error paths the pooling code has to survive without stranding state.
_BUILD_RAISES: set[str] = set()
_CLOSE_RAISES: set[str] = set()

_CREATED: list[_RecordingILOClient] = []


class _RecordingILOClient:
    """Stands in for ILOClient and records overlapping entries into poll()."""

    def __init__(self, host, username, password, ca_bundle=None):
        if host in _BUILD_RAISES:
            raise RuntimeError(f"cannot reach {host}")
        self.host = host
        self.username = username
        self._guard = threading.Lock()
        self.inside = 0
        self.max_inside = 0
        self.poll_count = 0
        self.closed = False
        _CREATED.append(self)
        gate = _BUILD_GATE.get(host)
        if gate is not None:
            entered, release = gate
            entered.set()
            release.wait(timeout=5)

    def poll(self) -> dict:
        with self._guard:
            self.inside += 1
            self.poll_count += 1
            self.max_inside = max(self.max_inside, self.inside)
        try:
            hold = _GATE["hold"]
            if hold is not None:
                # Park here until the test releases us, so a second caller has
                # to decide what to do about a client that is already in use.
                hold.wait(timeout=5)
            barrier = _GATE["barrier"]
            if barrier is not None:
                # Trips the instant every thread has arrived. If the code under
                # test serialises the callers instead, the first one waits out
                # the barrier's own timeout, breaks it, and the rest fall
                # straight through — so a correct implementation is fast too.
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
        finally:
            with self._guard:
                self.inside -= 1
        return {"health": "OK"}

    def get_status(self, _data: dict) -> str:
        return "healthy"

    def close(self) -> None:
        self.closed = True
        if self.host in _CLOSE_RAISES:
            raise OSError(f"socket for {self.host} already gone")


_CONFIG = {
    "profile": "ilo5",
    "host": "10.9.9.9",
    "username": "admin",
    "enabled": True,
}


def _hw(host: str = "10.9.9.9") -> SimpleNamespace:
    config = dict(_CONFIG)
    config["host"] = host
    return SimpleNamespace(id=4242, telemetry_config=config, ip_address=host)


class _NoVault:
    def decrypt(self, _value):  # pragma: no cover - no password in these configs
        raise AssertionError("these tests configure no password")


@pytest.fixture(autouse=True)
def _clean_dispatcher_cache(monkeypatch):
    # `_hw_client_cache` is the *whole* of the dispatcher's per-key client state:
    # each entry carries its own lock, so clearing the cache clears the locks
    # too. If a future change ever reintroduces a second module-level dict keyed
    # by cache key, this fixture has to clear that as well — and that need is
    # itself the warning sign, because a lock that can outlive its client is the
    # regression these tests exist to catch.
    monkeypatch.setitem(dispatcher.PROFILE_MAP, "ilo5", _RecordingILOClient)
    _reset_gates()
    dispatcher._hw_client_cache.clear()
    _CREATED.clear()
    yield
    _reset_gates()
    dispatcher._hw_client_cache.clear()
    _CREATED.clear()


def _reset_gates() -> None:
    for entered, release in _BUILD_GATE.values():
        # Never leave a constructor parked: a stranded builder holds its key's
        # lock and would push every later test onto the private-client path.
        entered.set()
        release.set()
    _BUILD_GATE.clear()
    _BUILD_RAISES.clear()
    _CLOSE_RAISES.clear()
    _GATE["barrier"] = None
    _GATE["hold"] = None


def _poll_in_threads(count: int) -> list[dict]:
    results: list[dict] = []
    results_lock = threading.Lock()

    def _run() -> None:
        out = dispatcher.poll_hardware(_hw(), _NoVault())
        with results_lock:
            results.append(out)

    threads = [threading.Thread(target=_run, name=f"poll-{i}") for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not [t for t in threads if t.is_alive()], "a poll thread never finished"
    return results


def test_concurrent_polls_never_put_two_threads_in_one_ilo_client():
    """The invariant R8 breaks: one client instance, at most one thread in poll()."""
    # Warm the cache the way steady-state operation does. Without this the
    # racing threads would each miss the empty cache and build their own
    # client, which hides the defect rather than exercising it.
    dispatcher.poll_hardware(_hw(), _NoVault())
    assert len(_CREATED) == 1, "warm-up should have cached exactly one client"

    workers = 4
    _GATE["barrier"] = threading.Barrier(workers, timeout=0.75)

    results = _poll_in_threads(workers)

    assert len(results) == workers
    assert all(r["status"] == "healthy" for r in results), results
    overlapped = [c for c in _CREATED if c.max_inside > 1]
    assert not overlapped, (
        "a cached ILOClient — and its requests.Session — was used by "
        f"{max(c.max_inside for c in overlapped)} threads at once"
    )


def test_sequential_polls_still_reuse_the_cached_client():
    """The fix must not be 'stop caching': that is what exhausts the pool.

    Read this one for what it does *not* pin. It passes against the R8 defect
    itself, and that is correct: R8 was over-sharing, and this asserts that
    sharing still happens in the case where sharing is safe. What it pins is the
    opposite failure, the tempting non-fix — make ``_pooled_client`` hand every
    caller a private client and every thread-safety test in this file goes
    green while every poll opens a fresh Redfish session against a BMC that
    tolerates a handful, which is the connection-pool exhaustion the cache was
    added for in the first place. So it checks all three things that non-fix
    would break: one client built, one client used for all five polls, and that
    client still pooled and still open at the end.
    """
    for _ in range(5):
        dispatcher.poll_hardware(_hw(), _NoVault())

    assert len(_CREATED) == 1, f"expected one pooled client, built {len(_CREATED)}"
    assert _CREATED[0].poll_count == 5
    assert not _CREATED[0].closed, "the reused client was closed; only private clients are"
    assert len(dispatcher._hw_client_cache) == 1, (
        "nothing was left in the cache, so the next poll cannot reuse anything"
    )


def test_a_poll_that_finds_the_cached_client_busy_gets_its_own(monkeypatch):
    """A stuck poll must not be able to hand its Session to the next caller.

    A manual poll that times out leaves its worker thread running — asyncio
    cannot interrupt a blocking socket read — so the cached client can stay in
    use for the device's full timeout. The next poll must not wait that out and
    must not join it: it gets a private client, and that client is closed so its
    sockets do not linger until the garbage collector notices.
    """
    monkeypatch.setattr(dispatcher, "_CLIENT_BUSY_WAIT_S", 0.05)

    dispatcher.poll_hardware(_hw(), _NoVault())
    cached = _CREATED[0]

    _GATE["hold"] = threading.Event()
    stuck = threading.Thread(target=lambda: dispatcher.poll_hardware(_hw(), _NoVault()))
    stuck.start()
    try:
        # Wait until the stuck thread is genuinely inside the cached client.
        for _ in range(200):
            if cached.inside == 1:
                break
            threading.Event().wait(0.01)
        assert cached.inside == 1, "the stuck poll never entered the cached client"

        _GATE["hold"] = None
        result = dispatcher.poll_hardware(_hw(), _NoVault())
    finally:
        gate = _GATE["hold"]
        if isinstance(gate, threading.Event):
            gate.set()
        _GATE["hold"] = None
        stuck.join(timeout=10)

    assert result["status"] == "healthy"
    assert cached.max_inside == 1, "the second poll joined the busy client"
    private = [c for c in _CREATED if c is not cached]
    assert len(private) == 1, f"expected one private fallback client, got {len(private)}"
    assert private[0].closed is True, "the private fallback client was never closed"


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        deadline.wait(0.01)
    return predicate()


def test_cache_eviction_during_a_build_does_not_share_a_client(monkeypatch):
    """An eviction must not be able to reunite two threads inside one Session.

    This is the second half of R8, and it survived the first fix. That fix kept
    the per-key locks in a ``_hw_client_locks`` dict parallel to the client
    cache. The eviction branch cleared the lock dict wholesale and re-registered
    only the *evicting* thread's key, but a client insert repopulated the client
    cache alone. So a thread that was still inside ``build()`` when someone
    else's key triggered an eviction went on to cache its client under a key
    that had no registered lock. The next caller for that key found no lock,
    minted a fresh one, acquired it uncontended, read the cache — and was handed
    the very client the first thread was still polling with. Two threads, one
    ``requests.Session``: exactly the defect, one dict-desync down.

    The cache size is monkeypatched down purely to make the eviction cheap to
    reach; the mechanism is identical at the real ``_HW_CLIENT_CACHE_MAX``.
    """
    monkeypatch.setattr(dispatcher, "_HW_CLIENT_CACHE_MAX", 2)
    # Short enough that if the fix ever regresses into "just wait for the other
    # thread", this test reports the sharing defect rather than timing out.
    monkeypatch.setattr(dispatcher, "_CLIENT_BUSY_WAIT_S", 0.05)

    entered_build = threading.Event()
    release_build = threading.Event()
    _BUILD_GATE["10.9.9.9"] = (entered_build, release_build)

    slow = threading.Thread(
        target=lambda: dispatcher.poll_hardware(_hw(), _NoVault()), name="slow-build"
    )
    slow.start()
    try:
        assert entered_build.wait(timeout=5), "the first poll never reached the constructor"

        # Fill the cache with unrelated keys until the eviction branch fires.
        # These run to completion on this thread, so they never overlap anything.
        for octet in (1, 2, 3):
            dispatcher.poll_hardware(_hw(host=f"10.9.9.{octet}"), _NoVault())
        assert len(dispatcher._hw_client_cache) < 3, "the eviction branch never fired"

        # Park the slow poll inside poll() the moment its constructor returns,
        # so it is provably still holding its client when the next caller lands.
        _GATE["hold"] = threading.Event()
        release_build.set()

        target = [c for c in _CREATED if c.host == "10.9.9.9"]
        assert _wait_until(lambda: any(c.inside == 1 for c in target)), (
            "the first poll never entered its client"
        )
        _GATE["hold"] = None

        dispatcher.poll_hardware(_hw(), _NoVault())
    finally:
        held = _GATE["hold"]
        if isinstance(held, threading.Event):
            held.set()
        _GATE["hold"] = None
        release_build.set()
        slow.join(timeout=10)

    assert not slow.is_alive(), "the first poll thread never finished"
    overlapped = [c for c in _CREATED if c.max_inside > 1]
    assert not overlapped, (
        "an evicted-then-recached ILOClient — and its requests.Session — was used by "
        f"{max(c.max_inside for c in overlapped)} threads at once"
    )


def test_a_failed_build_does_not_park_a_dead_entry_in_the_cache():
    """A client that cannot be constructed must leave no trace in the cache.

    The cache entry is published *before* the client is built so that the build
    is exclusive per key. That makes a build failure — an unreachable BMC, or
    ``_validate_lan_target`` rejecting a rebound host — able to leave a
    permanently client-less entry behind. If it did, every later poll of that
    key would find no client and be shunted onto the private-client path
    forever, and the key would hold a cache slot it can never use.
    """
    _BUILD_RAISES.add("10.9.9.9")
    failed = dispatcher.poll_hardware(_hw(), _NoVault())

    assert failed["status"] == "unknown"
    assert "cannot reach" in failed["error"]
    assert not dispatcher._hw_client_cache, (
        "a build that raised left an entry behind; the key is now permanently uncacheable"
    )

    # And the key must still be usable once the device comes back.
    _BUILD_RAISES.clear()
    ok = dispatcher.poll_hardware(_hw(), _NoVault())
    assert ok["status"] == "healthy"
    assert len(dispatcher._hw_client_cache) == 1
    assert dispatcher.poll_hardware(_hw(), _NoVault())["status"] == "healthy"
    assert len(_CREATED) == 1, "the recovered key is not being pooled"


def test_a_private_client_that_fails_to_close_is_logged_not_swallowed(monkeypatch, caplog):
    """A leaking close on the private path must not be silent.

    That close is the only thing handing back the socket a contended poll opened
    against a BMC. Swallowing its failure leaks exactly what the private-client
    path exists to prevent, and leaks it invisibly, so it is logged.
    """
    monkeypatch.setattr(dispatcher, "_CLIENT_BUSY_WAIT_S", 0.05)
    _CLOSE_RAISES.add("10.9.9.9")

    dispatcher.poll_hardware(_hw(), _NoVault())
    cached = _CREATED[0]

    _GATE["hold"] = threading.Event()
    stuck = threading.Thread(target=lambda: dispatcher.poll_hardware(_hw(), _NoVault()))
    stuck.start()
    try:
        assert _wait_until(lambda: cached.inside == 1), "the stuck poll never entered the client"
        _GATE["hold"] = None
        with caplog.at_level(logging.WARNING, logger=dispatcher._logger.name):
            result = dispatcher.poll_hardware(_hw(), _NoVault())
    finally:
        held = _GATE["hold"]
        if isinstance(held, threading.Event):
            held.set()
        _GATE["hold"] = None
        stuck.join(timeout=10)

    # The poll still succeeds: the caller is owed its data either way.
    assert result["status"] == "healthy"
    wanted = "Failed to close the private telemetry client"
    complaints = [r for r in caplog.records if wanted in r.getMessage()]
    assert complaints, (
        "the private client's close() raised and nothing was logged; "
        f"records seen: {[r.getMessage() for r in caplog.records]}"
    )
