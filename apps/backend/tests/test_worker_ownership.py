"""SRV-02/SRV-04: exactly one process runs each background job, provably.

Every scheduled job in this product mutates the one database all replicas
share. Registering them on each API process's own scheduler means "run this
once per process" — two uvicorn workers, an overlapping rolling restart, or an
API container beside a worker container, and the retention purge, the backup
and the integration sync all happen twice.

These tests do not simulate that with mocks. They run two independent
lock holders against the real PostgreSQL the suite starts, on separate
connections, and reconcile what actually executed.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.core.job_lock import (
    _lock_id_for,
    advisory_unlock,
    lock_session,
    single_owner,
    try_advisory_lock,
)


@pytest.fixture
def isolated_lock_name(request):
    """A lock name unique to the test, so a leaked lock cannot cross tests."""
    return f"test_{request.node.name}_{time.monotonic_ns()}"


def _run_concurrently(target, count: int) -> None:
    threads = [threading.Thread(target=target, name=f"owner-{i}") for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a lock holder never finished"


def test_two_processes_registering_the_same_job_execute_it_once(isolated_lock_name):
    """The SRV-02 claim, on real connections: two owners, one execution."""
    executions: list[str] = []
    both_attempted = threading.Barrier(2, timeout=30)
    executions_lock = threading.Lock()

    def job() -> None:
        with executions_lock:
            executions.append(threading.current_thread().name)
        # Hold the lock until the other replica has had its turn to try, so the
        # test cannot pass merely because the two attempts did not overlap.
        try:
            both_attempted.wait()
        except threading.BrokenBarrierError:  # pragma: no cover - timeout path
            pass

    guarded = single_owner(job, job_id=isolated_lock_name)

    def attempt() -> None:
        try:
            guarded()
        finally:
            try:
                both_attempted.wait(timeout=5)
            except (threading.BrokenBarrierError, threading.ThreadError):
                pass

    _run_concurrently(attempt, 2)

    assert len(executions) == 1, f"job ran {len(executions)} times: {executions}"


def test_the_loser_does_not_wait_for_the_owner(isolated_lock_name):
    """A replica that does not own the job returns immediately. Waiting would
    queue a second copy behind the first and defeat the point."""
    owner_db = lock_session()
    lock_id = _lock_id_for("scheduled_job", isolated_lock_name)
    assert try_advisory_lock(owner_db, lock_id)
    try:
        ran = []
        guarded = single_owner(lambda: ran.append(1), job_id=isolated_lock_name)

        started = time.monotonic()
        result = guarded()
        elapsed = time.monotonic() - started

        assert result is None
        assert ran == []
        assert elapsed < 5.0
    finally:
        advisory_unlock(owner_db, lock_id)
        owner_db.close()


def test_the_lease_hands_off_when_the_owner_finishes(isolated_lock_name):
    """SRV-04: a lease released by a departing process is taken by the next one
    — a rolling restart resumes the job rather than stranding it."""
    ran: list[str] = []
    guarded = single_owner(lambda: ran.append("run"), job_id=isolated_lock_name)

    owner_db = lock_session()
    lock_id = _lock_id_for("scheduled_job", isolated_lock_name)
    assert try_advisory_lock(owner_db, lock_id)
    guarded()
    assert ran == [], "a second process ran the job while the lease was held"

    # The owner goes away, exactly as a SIGTERMed process does.
    advisory_unlock(owner_db, lock_id)
    owner_db.close()

    guarded()
    assert ran == ["run"], "the lease was never picked up after the owner left"


def test_a_failing_job_releases_its_lease(isolated_lock_name):
    """A job that raises must not strand the lock; the next tick has to be able
    to run it, or one exception wedges the function forever."""

    def explode() -> None:
        raise RuntimeError("job failed")

    guarded = single_owner(explode, job_id=isolated_lock_name)
    with pytest.raises(RuntimeError):
        guarded()

    probe_db = lock_session()
    lock_id = _lock_id_for("scheduled_job", isolated_lock_name)
    try:
        assert try_advisory_lock(probe_db, lock_id), "lock still held after the job failed"
    finally:
        advisory_unlock(probe_db, lock_id)
        probe_db.close()


async def test_an_async_job_is_owned_for_its_whole_duration(isolated_lock_name):
    """Async jobs (the Proxmox polls, the audit-spool drain) must hold the lease
    across their awaits, not only while they are synchronously starting."""
    import asyncio
    import inspect

    lock_id = _lock_id_for("scheduled_job", isolated_lock_name)
    held_during_await: list[bool] = []

    async def job() -> None:
        probe_db = lock_session()
        try:
            # From another connection the lock must be unavailable.
            acquired = try_advisory_lock(probe_db, lock_id)
            held_during_await.append(not acquired)
            if acquired:
                advisory_unlock(probe_db, lock_id)
        finally:
            probe_db.close()
        await asyncio.sleep(0)

    guarded = single_owner(job, job_id=isolated_lock_name)
    assert inspect.iscoroutinefunction(guarded), "an async job must stay async for APScheduler"
    await guarded()

    assert held_during_await == [True]

    probe_db = lock_session()
    try:
        assert try_advisory_lock(probe_db, lock_id), "async job did not release its lease"
    finally:
        advisory_unlock(probe_db, lock_id)
        probe_db.close()


def test_the_scheduler_refuses_an_anonymous_job():
    """APScheduler would give an id-less job a fresh UUID in every process — a
    lock name that can never collide, and therefore an ownership guarantee that
    silently does not exist."""
    from app.core.scheduler import SingleOwnerScheduler

    scheduler = SingleOwnerScheduler()
    with pytest.raises(ValueError, match="explicit, stable job id"):
        scheduler.add_job(lambda: None, "interval", seconds=60)


def test_every_registered_startup_job_is_single_owner():
    """The guard is applied at registration, so a job added later inherits it.
    This asserts the wiring, which is what actually decays."""
    from app.core.scheduler import SingleOwnerScheduler

    scheduler = SingleOwnerScheduler()
    scheduler.add_job(lambda: None, "interval", seconds=60, id="test_ownership_probe")
    job = scheduler.get_job("test_ownership_probe")

    assert job is not None
    assert getattr(job.func, "cb_single_owner_job_id", None) == "test_ownership_probe"


def test_the_monitor_scheduler_clock_is_exclusive():
    """The polling engine's clock is single-instance by advisory lock. If two
    held it at once every monitor would be enqueued twice per tick."""
    from app.workers import monitor_scheduler

    lock_id = _lock_id_for(monitor_scheduler._LOCK_NAME)
    first = lock_session()
    second = lock_session()
    try:
        assert try_advisory_lock(first, lock_id)
        assert not try_advisory_lock(second, lock_id)
    finally:
        advisory_unlock(first, lock_id)
        first.close()
        second.close()
