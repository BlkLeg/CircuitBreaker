"""Slice 4 D-5: the owner of an agent discovery job nobody else will ever look at.

Three failures have no other owner in the product, and this suite is what pins
each of them:

* **A lease whose agent went silent.** `dispatch_deadline_at` passed and no
  terminal summary ever arrived. Nothing on the `/link` read loop fires for an
  agent that is not there, so without this pass the job stays `running`
  forever — holding a `discovery_scheduler._running_scan_count` slot while
  doing no work.
* **A job parked in `waiting_for_agent`.** D-5 deliberately leaves it `queued`
  so it consumes no slot, which also means no scheduler tick, no cron and no
  finalization ever looks at it again.
* **The `queued` backlog itself.** `discovery_scheduler._schedule_queued_scan_jobs`
  is called from exactly one place — `discovery_service._scan_finalize` — so a
  job that failed to claim a slot waits for some *other* job to finish, and a
  parked job waits for something that will never happen.

`monitoring/probe_reconcile` is the model for the expiry half and its grace is
derived, not restated: a finding must never be simultaneously "still
acceptable" to `agent_discovery.ingest_discovery_finding` and attached to a
dispatch this module already gave up on.

Two properties are raced on real connections rather than asserted sequentially,
for the reason `test_agent_discovery_dispatch.py` gives: driven one after the
other, both assertions pass against an implementation with no mutual exclusion
at all.
"""

import asyncio
import contextlib
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from app.core.time import utcnow, utcnow_iso
from app.db.models import Agent, ScanJob, ScanResult, Tenant
from app.schemas.agent_frame import TYPE_DISCOVERY_REQUEST
from app.services import (
    agent_discovery,
    agent_discovery_reconcile,
    agent_registry,
    discovery_service,
)

_SUBNET = "10.61.0.0/24"
_FACTS = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.61.0.5/24"]}]


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _tenant(db_session, name: str):  # type: ignore[no-untyped-def]
    tenant = Tenant(name=f"{name}-{secrets.token_hex(4)}")
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _agent(db_session, factories, *, tenant=None):  # type: ignore[no-untyped-def]
    """An agent that satisfies every §3 precondition, as in the dispatch suite."""
    tenant = tenant if tenant is not None else _tenant(db_session, "discovery-reconcile")
    agent = factories.agent(status="active", tenant_id=tenant.id)
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True, config={})
    factories.agent_network(agent, facts=_FACTS)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    db_session.flush()
    return agent


def _job(db_session, agent, **kwargs):  # type: ignore[no-untyped-def]
    defaults = {
        "scan_agent_id": None if agent is None else agent.id,
        "target_cidr": _SUBNET,
        "status": "queued",
        "scan_types_json": '["agent_connect"]',
        "source_type": "agent",
        "tenant_id": None if agent is None else agent.tenant_id,
        "created_at": utcnow_iso(),
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


def _parked(db_session, agent, *, deadline_at, **kwargs):  # type: ignore[no-untyped-def]
    """A job in exactly the state `agent_discovery._release_to_waiting` leaves it."""
    return _job(
        db_session,
        agent,
        status="queued",
        dispatch_status=agent_discovery.DISPATCH_STATUS_QUEUED,
        dispatch_id=None,
        scope_version=None,
        started_at=None,
        progress_phase=agent_discovery.PHASE_WAITING_FOR_AGENT,
        dispatch_deadline_at=deadline_at,
        **kwargs,
    )


def _leased(db_session, agent, *, deadline_at, **kwargs):  # type: ignore[no-untyped-def]
    """A job in exactly the state `agent_discovery._claim` leaves it."""
    return _job(
        db_session,
        agent,
        status="running",
        dispatch_status=agent_discovery.DISPATCH_STATUS_DISPATCHED,
        dispatch_id=secrets.token_hex(16),
        scope_version="v1",
        started_at=utcnow_iso(),
        progress_phase=agent_discovery.PHASE_DISPATCHED,
        dispatch_deadline_at=deadline_at,
        **kwargs,
    )


def _finding(db_session, job, ip: str = "10.61.0.9"):  # type: ignore[no-untyped-def]
    result = ScanResult(
        scan_job_id=job.id,
        discovery_agent_id=job.scan_agent_id,
        finding_id=secrets.token_hex(8),
        tenant_id=job.tenant_id,
        ip_address=ip,
        source_type="agent",
        created_at=utcnow_iso(),
    )
    db_session.add(result)
    db_session.flush()
    return result


@pytest.fixture
def online(monkeypatch):  # type: ignore[no-untyped-def]
    """The agent is back: presence, the bulk read this pass makes, and the
    connection owner the dispatcher's own eligibility check re-reads."""
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=True))
    monkeypatch.setattr(
        agent_registry, "get_agent_connection_owner", AsyncMock(return_value="worker-1")
    )
    monkeypatch.setattr(
        agent_registry,
        "bulk_presence",
        AsyncMock(side_effect=lambda ids: {i: {"online": True} for i in ids}),
    )


@pytest.fixture
def offline(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_registry, "get_agent_connection_owner", AsyncMock(return_value=None))
    monkeypatch.setattr(
        agent_registry,
        "bulk_presence",
        AsyncMock(side_effect=lambda ids: {i: {"online": False} for i in ids}),
    )


@pytest.fixture
def published(monkeypatch):  # type: ignore[no-untyped-def]
    frames: list[tuple[int, dict]] = []

    async def spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=spy))
    return frames


@pytest.fixture
def handed_off(monkeypatch):  # type: ignore[no-untyped-def]
    """Every job id handed to the ordinary fire-and-forget scan scheduler.

    Patched rather than allowed to run: `schedule_discovery_scan_job` starts a
    real `asyncio` task that runs a real nmap sweep, and every path that reaches
    it — this module's drain and `finalize_agent_job`'s own backlog drain — is
    the same module attribute, so one patch neutralizes both.
    """
    handled: list[int] = []
    monkeypatch.setattr(
        discovery_service, "schedule_discovery_scan_job", lambda job_id: handled.append(job_id)
    )
    return handled


def _requests(frames):  # type: ignore[no-untyped-def]
    return [f for _, f in frames if f["type"] == TYPE_DISCOVERY_REQUEST]


# ── The grace is derived, never restated ──────────────────────────────────────


def test_the_lease_grace_is_the_window_ingest_still_accepts_a_finding_in():
    """`monitoring/probe_reconcile`'s rule, for this lease: the moment a lease is
    written off must be the moment `agent_discovery` stops accepting findings
    against it. A second, independently-chosen number here would let a finding
    be refused as `late_finding` while its dispatch was still open, or accepted
    against a dispatch already given up on."""
    assert (
        agent_discovery_reconcile.LEASE_GRACE_S
        == agent_discovery.LATE_FINDING_GRACE.total_seconds()
    )


def test_the_waiting_horizon_is_the_dispatch_deadline_the_dispatcher_stamps():
    """D-5's parking horizon, borrowed from the module that stamps it, so a job
    parked with no `dispatch_deadline_at` of its own is still expired on the
    same clock as one that has one."""
    assert agent_discovery_reconcile.WAITING_HORIZON_S == agent_discovery.DISPATCH_DEADLINE_S


# ── A parked job whose agent came back ────────────────────────────────────────


async def test_a_reconnected_agent_gets_its_parked_job_dispatched_once(
    db_session, factories, online, published, handed_off
):
    """The retry-on-reconnect half of D-5, and it goes through the *normal*
    dispatcher: `dispatch_discovery_job` is what mints the token, snapshots
    `scope_version` and re-runs §3's preconditions, and a second copy of any of
    that here is a second answer to what the agent is allowed to scan."""
    agent = _agent(db_session, factories)
    job = _parked(db_session, agent, deadline_at=utcnow() + timedelta(seconds=300))

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.dispatched == 1
    assert len(_requests(published)) == 1
    db_session.refresh(job)
    assert job.status == "running"
    assert job.dispatch_status == agent_discovery.DISPATCH_STATUS_DISPATCHED
    assert job.dispatch_id is not None
    assert job.progress_phase == agent_discovery.PHASE_DISPATCHED


async def test_a_parked_job_whose_agent_is_still_away_keeps_its_original_deadline(
    db_session, factories, offline, published, handed_off
):
    """The treadmill this pass must not build. `_release_to_waiting` rewrites
    `dispatch_deadline_at` to `now + DISPATCH_DEADLINE_S` every time it runs, so
    a pass that handed every parked job back to the dispatcher would push the
    deadline forward once a minute and the job would never expire at all."""
    agent = _agent(db_session, factories)
    deadline = utcnow() + timedelta(seconds=300)
    job = _parked(db_session, agent, deadline_at=deadline)

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.dispatched == 0
    assert _requests(published) == []
    db_session.refresh(job)
    assert job.status == "queued"
    assert job.progress_phase == agent_discovery.PHASE_WAITING_FOR_AGENT
    assert abs((job.dispatch_deadline_at - deadline).total_seconds()) < 1


async def test_a_parked_job_past_its_deadline_fails_as_agent_unavailable(
    db_session, factories, offline, published, handed_off
):
    """D-4's vocabulary: the agent never turned up, so nothing was ever
    interrupted — `agent_unavailable`, not `agent_disconnected`."""
    agent = _agent(db_session, factories)
    job = _parked(db_session, agent, deadline_at=utcnow() - timedelta(seconds=1))

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.unavailable == 1
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_AGENT_UNAVAILABLE
    assert job.dispatch_status == agent_discovery_reconcile.DISPATCH_STATUS_EXPIRED
    assert _requests(published) == []


async def test_a_parked_job_past_its_deadline_is_expired_even_though_its_agent_is_back(
    db_session, factories, online, published, handed_off
):
    """Expiry runs before the retry, and has to: a job whose deadline has passed
    is one an operator has already been told nothing about for fifteen minutes,
    and dispatching it now would start a sweep whose findings the ingest path
    would judge against a lease it had no reason to expect."""
    agent = _agent(db_session, factories)
    job = _parked(db_session, agent, deadline_at=utcnow() - timedelta(seconds=1))

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert (summary.unavailable, summary.dispatched) == (1, 0)
    assert _requests(published) == []
    db_session.refresh(job)
    assert job.status == "failed"


async def test_a_parked_job_with_no_deadline_of_its_own_is_still_on_a_clock(
    db_session, factories, offline, published, handed_off
):
    """`probe_reconcile`'s `coalesce(deadline_at, scheduled_at)`, for this table.
    A row whose `dispatch_deadline_at` was never written — an older revision, or
    a claim that never happened — must not be immortal, and D-5's own
    `DISPATCH_DEADLINE_S` measured from the job's creation is the clock it gets.
    """
    agent = _agent(db_session, factories)
    stale_by = agent_discovery_reconcile.WAITING_HORIZON_S + 60
    old = _parked(
        db_session,
        agent,
        deadline_at=None,
        created_at=(utcnow() - timedelta(seconds=stale_by)).isoformat(),
    )
    fresh = _parked(db_session, agent, deadline_at=None, created_at=utcnow_iso())

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.unavailable == 1
    db_session.refresh(old)
    db_session.refresh(fresh)
    assert old.status == "failed"
    assert old.error_reason == agent_discovery.ERROR_AGENT_UNAVAILABLE
    assert fresh.status == "queued"


# ── A lease whose agent went silent ───────────────────────────────────────────


async def test_an_expired_lease_fails_as_agent_disconnected_and_keeps_its_findings(
    db_session, factories, offline, published, handed_off
):
    """D-4 in full. There is no `partial` status, so an interrupted scan is
    `failed` — and the rows the agent did send stay exactly where they are,
    pending review, because they describe hosts that really were observed."""
    agent = _agent(db_session, factories)
    job = _leased(
        db_session,
        agent,
        deadline_at=utcnow() - agent_discovery.LATE_FINDING_GRACE - timedelta(seconds=1),
        hosts_found=2,
        finding_count=2,
    )
    kept = [_finding(db_session, job, "10.61.0.9"), _finding(db_session, job, "10.61.0.10")]

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.disconnected == 1
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_AGENT_DISCONNECTED
    assert job.dispatch_status == agent_discovery_reconcile.DISPATCH_STATUS_EXPIRED
    # The counters the ingest path accumulated are not rewritten either (D-10).
    assert (job.hosts_found, job.finding_count) == (2, 2)
    surviving = db_session.query(ScanResult).filter(ScanResult.scan_job_id == job.id).all()
    assert {r.id for r in surviving} == {r.id for r in kept}
    assert {r.merge_status for r in surviving} == {"pending"}


async def test_a_lease_inside_the_late_finding_grace_is_left_alone(
    db_session, factories, offline, published, handed_off
):
    """The grace is not decoration: within it a spooled finding is still
    acceptable to `ingest_discovery_finding`, and expiring the lease here would
    make the same frame a `late_finding` rejection against a job the server had
    already closed."""
    agent = _agent(db_session, factories)
    job = _leased(
        db_session,
        agent,
        deadline_at=utcnow() - agent_discovery.LATE_FINDING_GRACE + timedelta(seconds=10),
    )

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.disconnected == 0
    db_session.refresh(job)
    assert job.status == "running"
    assert job.dispatch_status == agent_discovery.DISPATCH_STATUS_DISPATCHED


async def test_a_live_lease_inside_its_deadline_is_left_alone(
    db_session, factories, offline, published, handed_off
):
    agent = _agent(db_session, factories)
    job = _leased(db_session, agent, deadline_at=utcnow() + timedelta(seconds=600))

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.disconnected == 0
    db_session.refresh(job)
    assert job.status == "running"


# ── A finished job is finished ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "dispatch_status"),
    [
        ("completed", agent_discovery.DISPATCH_STATUS_COMPLETED),
        ("cancelled", agent_discovery.DISPATCH_STATUS_CANCELLED),
        ("failed", agent_discovery.DISPATCH_STATUS_EXECUTION_ERROR),
    ],
)
async def test_a_terminal_job_is_never_replayed(
    db_session, factories, online, published, handed_off, status, dispatch_status
):
    """Whatever its deadline says. A completed job's summary already landed, a
    cancelled one was taken away deliberately, and re-dispatching either would
    sweep a subnet nobody asked about and reopen a closed audit trail."""
    agent = _agent(db_session, factories)
    job = _job(
        db_session,
        agent,
        status=status,
        dispatch_status=dispatch_status,
        dispatch_id=secrets.token_hex(16),
        dispatch_deadline_at=utcnow() - timedelta(days=1),
        completed_at=utcnow_iso(),
        progress_phase="done",
    )

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert (summary.disconnected, summary.unavailable, summary.dispatched) == (0, 0, 0)
    assert _requests(published) == []
    assert handed_off == []
    db_session.refresh(job)
    assert job.status == status
    assert job.dispatch_status == dispatch_status
    assert job.completed_at is not None


async def test_a_terminal_server_job_is_never_handed_back_to_the_scan_scheduler(
    db_session, factories, online, published, handed_off
):
    """The drain's own `status == 'queued'` filter, and it is the only thing
    standing here. An agent job is caught a second time by the dispatcher, which
    refuses anything that is not queued; a server job is fired and forgotten
    through `schedule_discovery_scan_job`, which asks no such question — so
    dropping the filter would re-run every finished nmap sweep in the history
    table, once per interval, forever.
    """
    job = _job(
        db_session,
        None,
        source_type="manual",
        scan_types_json='["nmap"]',
        status="completed",
        completed_at=utcnow_iso(),
        progress_phase="done",
    )

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert handed_off == []
    assert summary.scheduled == 0
    db_session.refresh(job)
    assert job.status == "completed"


async def test_a_terminal_job_parked_phase_is_not_resurrected_by_the_drain(
    db_session, factories, online, published, handed_off
):
    """A cancelled job keeps whatever `progress_phase` it had when it was taken
    away, so the drain must select on `status`, never on the phase alone."""
    agent = _agent(db_session, factories)
    job = _job(
        db_session,
        agent,
        status="cancelled",
        dispatch_status=agent_discovery.DISPATCH_STATUS_CANCELLED,
        progress_phase=agent_discovery.PHASE_WAITING_FOR_AGENT,
        dispatch_deadline_at=utcnow() + timedelta(seconds=300),
    )

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert (summary.dispatched, summary.unavailable) == (0, 0)
    assert _requests(published) == []
    db_session.refresh(job)
    assert job.status == "cancelled"


# ── The queued backlog ────────────────────────────────────────────────────────


async def test_a_never_claimed_agent_job_is_drained_rather_than_stranded(
    db_session, factories, online, published, handed_off
):
    """The hole D-5 names: `_schedule_queued_scan_jobs` runs only from
    `_scan_finalize`, so a job that failed to claim a slot waits for some other
    job to finish, and on an idle server that is forever."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, progress_phase="queued")

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.dispatched == 1
    assert len(_requests(published)) == 1
    db_session.refresh(job)
    assert job.status == "running"


async def test_a_queued_server_job_is_handed_to_the_ordinary_scan_scheduler(
    db_session, factories, online, published, handed_off
):
    """The backlog is the whole backlog. A server scan is fire-and-forget —
    awaiting an nmap sweep would hold the advisory lock for its whole duration —
    so it goes through the same entry point `_scan_finalize` uses."""
    _agent(db_session, factories)
    job = _job(db_session, None, source_type="manual", scan_types_json='["nmap"]')

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert handed_off == [job.id]
    assert summary.scheduled == 1
    assert _requests(published) == []


async def test_the_drain_respects_the_concurrency_ceiling(
    db_session, factories, online, published, handed_off
):
    """A dispatched agent job is `running` and therefore counts against
    `max_concurrent_scans` exactly as a server scan does; a drain that ignored
    the ceiling would start every queued scan on the fleet at once."""
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db_session)
    settings.max_concurrent_scans = 1
    db_session.flush()

    agent = _agent(db_session, factories)
    first = _job(db_session, agent, created_at="2020-01-01T00:00:00+00:00")
    second = _job(db_session, agent, created_at="2020-01-02T00:00:00+00:00")

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert summary.dispatched == 1
    assert len(_requests(published)) == 1
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.status == "running"
    assert second.status == "queued"


async def test_expiry_frees_the_slot_the_drain_then_uses(
    db_session, factories, online, published, handed_off
):
    """Why expiry runs first. The dead lease is holding the only slot; a pass
    that drained before expiring would find none free and make no progress at
    all until the next tick."""
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db_session)
    settings.max_concurrent_scans = 1
    db_session.flush()

    agent = _agent(db_session, factories)
    dead = _leased(
        db_session,
        agent,
        deadline_at=utcnow() - agent_discovery.LATE_FINDING_GRACE - timedelta(seconds=60),
    )
    waiting = _job(db_session, agent)

    summary = await agent_discovery_reconcile.reconcile(db_session)

    assert (summary.disconnected, summary.dispatched) == (1, 1)
    db_session.refresh(dead)
    db_session.refresh(waiting)
    assert dead.status == "failed"
    assert waiting.status == "running"


# ── Two real sessions ─────────────────────────────────────────────────────────


@contextlib.contextmanager
def _committed_agent_job(**job_kwargs):  # type: ignore[no-untyped-def]
    """One agent job on its own connection, cleaned up afterwards.

    `db_session`'s SAVEPOINT is invisible to a second connection, so a race can
    only be run against rows that are really committed — the pattern
    `test_agent_discovery_dispatch.py` uses for the same reason.
    """
    from app.db.session import SessionLocal
    from tests.factories import Factories

    with SessionLocal() as setup:
        tenant = Tenant(name=f"discovery-reconcile-race-{secrets.token_hex(4)}")
        setup.add(tenant)
        setup.flush()
        factories = Factories(setup)
        agent = factories.agent(status="active", tenant_id=tenant.id)
        factories.agent_capability_grant(
            agent, capability="local_discovery", enabled=True, config={}
        )
        factories.agent_network(agent, facts=_FACTS)
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
        defaults = {
            "scan_agent_id": agent.id,
            "target_cidr": _SUBNET,
            "status": "queued",
            "scan_types_json": '["agent_connect"]',
            "source_type": "agent",
            "tenant_id": tenant.id,
            "created_at": utcnow_iso(),
        }
        defaults.update(job_kwargs)
        job = ScanJob(**defaults)
        setup.add(job)
        setup.commit()
        ids = (agent.id, job.id, tenant.id)

    try:
        yield ids
    finally:
        agent_id, job_id, tenant_id = ids
        with SessionLocal() as cleanup:
            cleanup.execute(delete(ScanResult).where(ScanResult.scan_job_id == job_id))
            cleanup.execute(delete(ScanJob).where(ScanJob.id == job_id))
            cleanup.execute(delete(Agent).where(Agent.id == agent_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()


def _race() -> list:  # type: ignore[type-arg]
    """Run two whole reconcile passes on two real connections, at once."""
    from app.db.session import SessionLocal

    def _pass(_n: int):  # type: ignore[no-untyped-def]
        with SessionLocal() as session:
            return asyncio.run(agent_discovery_reconcile.reconcile(session))

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(_pass, [0, 1]))


def test_two_real_workers_expire_one_dead_lease_exactly_once(setup_db, monkeypatch) -> None:
    """The advisory lock makes this impossible in production; the pass has to be
    idempotent anyway, because a lock is a lock on the *usual* case — a replica
    restarting, a misfire replay and a manual invocation all overlap it — and
    because a second finalization means a second `scan_failed` audit row and a
    second terminal `job_update` for a job that only failed once.

    Driven sequentially this assertion passes against a plain read-then-write:
    the first pass commits before the second reads, and the second simply finds
    nothing to do.
    """
    barrier = threading.Barrier(2)
    original = discovery_service.finalize_agent_job

    async def barriered(db, job, status, **kwargs):  # type: ignore[no-untyped-def]
        # Inside the pass, after selection and before the compare-and-set: the
        # window the two workers must both be in for the CAS to be the thing
        # under test rather than the ordering of two sequential transactions.
        barrier.wait(timeout=10)
        return await original(db, job, status, **kwargs)

    monkeypatch.setattr(discovery_service, "finalize_agent_job", barriered)
    monkeypatch.setattr(discovery_service, "schedule_discovery_scan_job", lambda job_id: None)
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_registry, "get_agent_connection_owner", AsyncMock(return_value=None))
    monkeypatch.setattr(
        agent_registry,
        "bulk_presence",
        AsyncMock(side_effect=lambda ids: {i: {"online": False} for i in ids}),
    )

    stale = utcnow() - agent_discovery.LATE_FINDING_GRACE - timedelta(seconds=60)
    with _committed_agent_job(
        status="running",
        dispatch_status=agent_discovery.DISPATCH_STATUS_DISPATCHED,
        dispatch_id=secrets.token_hex(16),
        dispatch_deadline_at=stale,
        progress_phase=agent_discovery.PHASE_DISPATCHED,
    ) as (_agent_id, job_id, _tenant_id):
        summaries = _race()

        assert sum(s.disconnected for s in summaries) == 1, summaries

        from app.db.session import SessionLocal

        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.status == "failed"
            assert stored.error_reason == agent_discovery.ERROR_AGENT_DISCONNECTED
            assert stored.dispatch_status == agent_discovery_reconcile.DISPATCH_STATUS_EXPIRED


def test_two_real_workers_retry_one_parked_job_exactly_once(setup_db, monkeypatch) -> None:
    """The other half. Two `discovery.request` frames for one job means two
    sweeps of the subnet, two terminal summaries and a second dispatch token
    whose findings the first summary's finalization refuses at random — the
    exact failure `dispatch_discovery_job`'s compare-and-set exists to stop, and
    reusing that dispatcher rather than restating a claim here is what buys it.
    """
    frames: list[dict] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    derive = agent_discovery.derive_discovery_scope

    def barriered_derive(db, agent_id, config=None):  # type: ignore[no-untyped-def]
        scope = derive(db, agent_id, config)
        barrier.wait(timeout=10)
        return scope

    async def spy(agent_id: int, frame: dict) -> bool:
        with lock:
            frames.append(frame)
        return True

    monkeypatch.setattr(agent_discovery, "derive_discovery_scope", barriered_derive)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=spy))
    monkeypatch.setattr(discovery_service, "schedule_discovery_scan_job", lambda job_id: None)
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=True))
    monkeypatch.setattr(
        agent_registry, "get_agent_connection_owner", AsyncMock(return_value="worker-1")
    )
    monkeypatch.setattr(
        agent_registry,
        "bulk_presence",
        AsyncMock(side_effect=lambda ids: {i: {"online": True} for i in ids}),
    )

    with _committed_agent_job(
        status="queued",
        dispatch_status=agent_discovery.DISPATCH_STATUS_QUEUED,
        progress_phase=agent_discovery.PHASE_WAITING_FOR_AGENT,
        dispatch_deadline_at=utcnow() + timedelta(seconds=600),
    ) as (_agent_id, job_id, _tenant_id):
        summaries = _race()

        assert sum(s.dispatched for s in summaries) == 1, summaries
        requests = [f for f in frames if f["type"] == TYPE_DISCOVERY_REQUEST]
        assert len(requests) == 1, requests

        from app.db.session import SessionLocal

        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.status == "running"
            assert stored.dispatch_id == requests[0]["payload"]["dispatch_id"]


# ── The scheduled entry point ─────────────────────────────────────────────────


async def test_the_scheduled_pass_runs_on_the_event_loop_holding_its_own_lock(
    setup_db, monkeypatch
) -> None:
    """Both halves of the registration contract, in one pass.

    **On the loop**, because the drain calls
    `discovery_service.schedule_discovery_scan_job`, which starts the
    server-scan executor with `asyncio.create_task` — that raises where there is
    no running loop, and it is a live defect on the neighbouring path
    (`_scan_finalize` calls the same drain from a `run_in_executor` worker
    thread). A synchronous APScheduler job would run in the scheduler's thread
    pool and reproduce it here.

    **Holding `agent_discovery_reconcile`**, because unlike
    `monitoring/probe_reconcile` — which rides `monitor_scheduler.tick` and
    deliberately holds no lock, since that tick already holds the one lock —
    this pass runs standalone and every replica would otherwise expire and
    re-dispatch the same jobs at once. Proved by failing to take the same lock
    from a second connection while the pass is mid-flight, which is the only
    thing that distinguishes a held lock from a lock that was never taken.
    """
    from app.core.job_lock import _lock_id_for, advisory_unlock, try_advisory_lock
    from app.db.session import SessionLocal

    lock_id = _lock_id_for(agent_discovery_reconcile.LOCK_NAME)
    observed: dict = {}

    async def spy() -> None:
        observed["loop"] = asyncio.get_running_loop()
        with SessionLocal() as probe:
            observed["taken_twice"] = try_advisory_lock(probe, lock_id)
            if observed["taken_twice"]:
                advisory_unlock(probe, lock_id)

    monkeypatch.setattr(agent_discovery_reconcile, "_reconcile_once", spy)

    await agent_discovery_reconcile.run_agent_discovery_reconciliation()

    assert observed["loop"] is asyncio.get_running_loop()
    assert observed["taken_twice"] is False

    # And it is given back: a lock leaked by one pass would silence every
    # later one on every replica, with no symptom but jobs that never expire.
    with SessionLocal() as after:
        assert try_advisory_lock(after, lock_id) is True
        advisory_unlock(after, lock_id)


async def test_a_failing_pass_still_releases_the_lock(setup_db, monkeypatch) -> None:
    """`monitor_scheduler.tick` guards its call into `probe_reconcile` for the
    same reason: a reconciliation defect must not be able to wedge the thing
    that is supposed to unwedge everything else."""
    from app.core.job_lock import _lock_id_for, advisory_unlock, try_advisory_lock
    from app.db.session import SessionLocal

    lock_id = _lock_id_for(agent_discovery_reconcile.LOCK_NAME)

    async def boom(db, *, now=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("reconcile blew up")

    monkeypatch.setattr(agent_discovery_reconcile, "reconcile", boom)

    await agent_discovery_reconcile.run_agent_discovery_reconciliation()

    with SessionLocal() as after:
        assert try_advisory_lock(after, lock_id) is True
        advisory_unlock(after, lock_id)


# ── D-5's boundary ────────────────────────────────────────────────────────────


def test_this_module_does_not_import_the_readiness_reconciler():
    """D-5 is explicit: `services/discovery_reconciler.py` is untouched by this
    slice and no finding path may import it. It heals discovery *readiness*
    (nmap capability) and touches no `ScanJob` row, and folding scan-job
    lifecycle into it is exactly what plan §5 means by "do not route agent
    findings into the reconciler". Asserted against the source rather than
    against `sys.modules`, which some other test's import would pollute.
    """
    import ast

    source = Path(agent_discovery_reconcile.__file__).read_text()
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(f"{node.module or ''}.{alias.name}" for alias in node.names)

    assert not [name for name in imported if "discovery_reconciler" in name], imported


def test_the_interval_job_is_registered_in_the_lifespan_and_not_in_reload_discovery_jobs():
    """`core.scheduler.reload_discovery_jobs` is re-invoked on every profile
    write and *first removes every job it registered*, so anything registered
    there is silently unregistered the next time an administrator saves a
    profile — the failure mode has no symptom until a dispatch is never
    expired. The lifespan registers it once, under its own advisory lock.
    """
    backend = Path(__file__).resolve().parents[2]
    main_py = (backend / "src/app/main.py").read_text()
    scheduler_py = (backend / "src/app/core/scheduler.py").read_text()

    assert f'id="{agent_discovery_reconcile.LOCK_NAME}"' in main_py
    assert "run_agent_discovery_reconciliation" in main_py
    assert "agent_discovery_reconcile" not in scheduler_py
