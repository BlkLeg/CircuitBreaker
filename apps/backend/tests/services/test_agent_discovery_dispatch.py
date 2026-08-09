"""Slice 4 §3/§4: routing a discovery job to an agent, and the dispatch lease.

`workers/monitor_probe_dispatch.py` is the model — the same shape of worker turns
one queued row into one delivered control frame, closes it when the vantage
cannot run it, and never lets an undeliverable frame leave the row open. Three
things differ, each because discovery differs, and each is pinned below:

* **The lease lives on the job row**, not on a row of its own. There is
  therefore no `uq_..._active_dispatch` to lean on (`db/models.py` and migration
  `0100` both say why): two workers racing both read `dispatch_status IS NULL`,
  and only a conditional UPDATE stops the second. So the claim is a
  compare-and-set with a rowcount check, `uq_scan_jobs_dispatch_id` makes a
  duplicated token an integrity error, and both are raced on two real
  connections here because the sequential version of either assertion passes
  against a read-modify-write.
* **An offline agent parks the job rather than failing it** (D-5), and it must
  give the claim back while it waits: `discovery_scheduler._running_scan_count`
  counts `status == "running"`, so a job left running while it waits for an
  agent starves every other scan for the whole deadline.
* **Validation happens twice.** Task 19 validated the request when it was
  written; scope is derived from what the agent reports about its own
  interfaces, so it can move between then and now. The dispatch-time check is
  in addition to that one and never instead of it.
"""

import asyncio
import contextlib
import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow, utcnow_iso
from app.db.models import Agent, AgentNetwork, DiscoveryProfile, ScanJob, ScanResult, Tenant
from app.schemas.agent_frame import (
    MAX_DISCOVERY_TARGETS,
    TYPE_DISCOVERY_REQUEST,
    DiscoveryRequestPayload,
)
from app.services import (
    agent_discovery,
    agent_registry,
    discovery_eligibility,
    discovery_scheduler,
    discovery_service,
)

_SUBNET = "10.60.0.0/24"
_FACTS = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.60.0.5/24"]}]
_DISPATCH_ID_RE = re.compile(r"[0-9a-f]{32}")


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _tenant(db_session, name: str):  # type: ignore[no-untyped-def]
    tenant = Tenant(name=f"{name}-{secrets.token_hex(4)}")
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _agent(db_session, factories, *, config=None, facts=None, readiness="ready", tenant=None):  # type: ignore[no-untyped-def]
    """An agent that satisfies every §3 precondition — tests remove one at a time."""
    tenant = tenant if tenant is not None else _tenant(db_session, "discovery-dispatch")
    agent = factories.agent(status="active", tenant_id=tenant.id)
    factories.agent_capability_grant(
        agent, capability="local_discovery", enabled=True, config=config or {}
    )
    factories.agent_network(agent, facts=_FACTS if facts is None else facts)
    if readiness is not None:
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state=readiness)
    db_session.flush()
    return agent


def _job(db_session, agent, **kwargs):  # type: ignore[no-untyped-def]
    """A queued agent job, in the state `create_scan_job` leaves it in."""
    defaults = {
        "scan_agent_id": agent.id,
        "target_cidr": _SUBNET,
        "status": "queued",
        "scan_types_json": '["agent_connect"]',
        "source_type": "agent",
        "tenant_id": agent.tenant_id,
        "created_at": utcnow_iso(),
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


@pytest.fixture
def online(monkeypatch):  # type: ignore[no-untyped-def]
    """Presence and connection ownership, the two Redis reads `require_online`
    makes. Both are patched because `discovery_eligibility` refuses on either."""
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=True))
    monkeypatch.setattr(
        agent_registry, "get_agent_connection_owner", AsyncMock(return_value="worker-1")
    )


@pytest.fixture
def offline(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_registry, "get_agent_connection_owner", AsyncMock(return_value=None))


@pytest.fixture
def published(monkeypatch):  # type: ignore[no-untyped-def]
    """Every control frame this dispatch would put on the wire."""
    frames: list[tuple[int, dict]] = []

    async def spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=spy))
    return frames


@pytest.fixture
def undeliverable(monkeypatch):  # type: ignore[no-untyped-def]
    """`publish_agent_control_frame` returns False only when Redis itself is
    unavailable, so nothing can have arrived."""
    monkeypatch.setattr(
        agent_registry, "publish_agent_control_frame", AsyncMock(return_value=False)
    )


def _request(frames):  # type: ignore[no-untyped-def]
    """The one `discovery.request` payload these frames carry."""
    requests = [f for _, f in frames if f["type"] == TYPE_DISCOVERY_REQUEST]
    assert len(requests) == 1, frames
    return requests[0]["payload"]


# ── create_scan_job persists the execution location ───────────────────────────


def test_creating_an_agent_job_persists_the_execution_location(db_session, factories):
    """Task 19 validated `scan_agent_id` and deliberately dropped it; without it
    on the row nothing downstream can route the job anywhere but the server
    scanner, and plan §3 forbids that fallback outright."""
    agent = _agent(db_session, factories)

    job = discovery_service.create_scan_job(
        db_session, target_cidr=_SUBNET, scan_types=["agent_connect"], scan_agent_id=agent.id
    )

    assert job.scan_agent_id == agent.id
    assert job.source_type == discovery_service.SOURCE_TYPE_AGENT
    # D-17: tenant is derived from the agent, never accepted from a request.
    assert job.tenant_id == agent.tenant_id
    assert job.tenant_id is not None


def test_creating_a_server_job_names_no_agent_and_keeps_its_source_type(
    db_session, factories, nmap_enabled
):
    """`scan_agent_id is None` is every job that predates Slice 4."""
    _agent(db_session, factories)

    job = discovery_service.create_scan_job(db_session, target_cidr=_SUBNET, scan_types=["nmap"])

    assert job.scan_agent_id is None
    assert job.source_type != discovery_service.SOURCE_TYPE_AGENT
    assert job.tenant_id is None


def test_creation_time_validation_still_runs_when_the_job_is_persisted(
    db_session, factories, monkeypatch
):
    """In addition to the dispatch-time re-check, never instead of it: routing
    the job must not have quietly replaced §3's first checkpoint."""
    calls: list[int | None] = []
    original = discovery_service.validate_agent_execution_location

    def spy(db, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs.get("scan_agent_id"))
        return original(db, **kwargs)

    monkeypatch.setattr(discovery_service, "validate_agent_execution_location", spy)
    agent = _agent(db_session, factories)

    discovery_service.create_scan_job(
        db_session, target_cidr=_SUBNET, scan_types=["agent_connect"], scan_agent_id=agent.id
    )

    assert calls == [agent.id]


# ── Routing: an agent job never reaches the server scanner ────────────────────


@pytest.fixture
def server_scanner(monkeypatch):  # type: ignore[no-untyped-def]
    """Spies on both halves of the server executor.

    `_scan_setup` as well as `run_scan_job`, because the phase split means a
    router that called the wrong one would still look inert from the outside
    until it marked the job `running` and started sweeping.
    """
    entered: list[str] = []
    monkeypatch.setattr(
        discovery_service,
        "run_scan_job",
        AsyncMock(side_effect=lambda job_id: entered.append("run_scan_job")),
    )
    monkeypatch.setattr(
        discovery_service, "_scan_setup", lambda job_id: entered.append("_scan_setup")
    )
    return entered


@pytest.fixture
def dispatcher(monkeypatch):  # type: ignore[no-untyped-def]
    dispatched: list[int] = []

    async def spy(db, job_id):  # type: ignore[no-untyped-def]
        dispatched.append(job_id)
        return True

    monkeypatch.setattr(agent_discovery, "dispatch_discovery_job", AsyncMock(side_effect=spy))
    return dispatched


async def test_an_agent_job_routes_to_the_dispatcher_and_not_the_server_scanner(
    db_session, factories, server_scanner, dispatcher
):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    await discovery_service.execute_scan_job(db_session, job.id)

    assert dispatcher == [job.id]
    assert server_scanner == []


async def test_a_server_job_still_routes_to_the_server_scanner(
    db_session, factories, server_scanner, dispatcher
):
    """The branch has to be a branch: a router that sent everything to the
    agent dispatcher would pass every assertion above."""
    job = _job(db_session, _agent(db_session, factories), scan_agent_id=None, source_type="manual")

    await discovery_service.execute_scan_job(db_session, job.id)

    assert dispatcher == []
    assert server_scanner == ["run_scan_job"]


# ── Routing: a scheduled agent profile ────────────────────────────────────────


@contextlib.contextmanager
def _committed_agent_profile(**profile_kwargs):  # type: ignore[no-untyped-def]
    """An agent and its profile, committed on their own connection.

    `discovery_scheduler._run_profile_job_async` opens its own `SessionLocal`,
    which cannot see `db_session`'s SAVEPOINT — the pattern
    `tests/api/test_ws_agents_enroll.py` documents. Nothing rolls a real commit
    back either, so the rows are deleted again in `finally`.
    """
    from app.db.session import SessionLocal
    from tests.factories import Factories

    with SessionLocal() as setup:
        tenant = Tenant(name=f"discovery-cron-{secrets.token_hex(4)}")
        setup.add(tenant)
        setup.flush()
        factories = Factories(setup)
        agent = factories.agent(status="active", tenant_id=tenant.id)
        factories.agent_capability_grant(
            agent, capability="local_discovery", enabled=True, config={}
        )
        factories.agent_network(agent, facts=_FACTS)
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
        now = utcnow_iso()
        defaults = {
            "name": f"agent-subnet-{secrets.token_hex(4)}",
            "cidr": _SUBNET,
            "scan_types": '["agent_connect"]',
            "scan_agent_id": agent.id,
            "enabled": 1,
            "created_at": now,
            "updated_at": now,
        }
        defaults.update(profile_kwargs)
        profile = DiscoveryProfile(**defaults)
        setup.add(profile)
        setup.commit()
        ids = (agent.id, profile.id, tenant.id)

    try:
        yield ids
    finally:
        agent_id, profile_id, tenant_id = ids
        with SessionLocal() as cleanup:
            job_ids = [
                row[0]
                for row in cleanup.execute(
                    ScanJob.__table__.select().with_only_columns(ScanJob.id)
                ).all()
                if cleanup.get(ScanJob, row[0]).profile_id == profile_id
            ]
            if job_ids:
                cleanup.execute(delete(ScanResult).where(ScanResult.scan_job_id.in_(job_ids)))
                cleanup.execute(delete(ScanJob).where(ScanJob.id.in_(job_ids)))
            cleanup.execute(delete(DiscoveryProfile).where(DiscoveryProfile.id == profile_id))
            cleanup.execute(delete(Agent).where(Agent.id == agent_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()


async def test_a_scheduled_agent_profile_produces_an_agent_job_with_no_server_activity(
    setup_db, server_scanner, dispatcher
):
    """Plan §3's cron path. `_run_profile_job_async` called `run_scan_job`
    directly, so the profile's execution location was lost twice over: the job
    it built never carried `scan_agent_id`, and nothing consulted it anyway."""
    from app.db.session import SessionLocal

    with _committed_agent_profile() as (agent_id, profile_id, _tenant_id):
        await discovery_scheduler._run_profile_job_async(profile_id)

        with SessionLocal() as check:
            jobs = [
                job for job in check.query(ScanJob).filter(ScanJob.profile_id == profile_id).all()
            ]
        assert len(jobs) == 1, jobs
        assert jobs[0].scan_agent_id == agent_id
        assert jobs[0].source_type == discovery_service.SOURCE_TYPE_AGENT
        assert dispatcher == [jobs[0].id]
        assert server_scanner == []


# ── Claiming, and the one request it publishes ────────────────────────────────


async def test_claiming_mints_a_dispatch_and_publishes_exactly_one_request(
    db_session, factories, online, published
):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is True

    db_session.refresh(job)
    assert _DISPATCH_ID_RE.fullmatch(job.dispatch_id), job.dispatch_id
    assert job.dispatch_status == agent_discovery.DISPATCH_STATUS_DISPATCHED
    assert job.status == "running"
    assert job.dispatch_deadline_at is not None
    payload = _request(published)
    assert payload["dispatch_id"] == job.dispatch_id
    assert payload["scan_job_id"] == job.id
    assert published[0][0] == agent.id


async def test_the_dispatched_scope_version_is_written_and_shipped_together(
    db_session, factories, online, published
):
    """D-16. The job's snapshot and the agent's copy are the same string, or
    ingest — which judges a finding against `job.scope_version` — is judging it
    against a scope the agent was never told about."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    await agent_discovery.dispatch_discovery_job(db_session, job.id)

    db_session.refresh(job)
    expected = agent_discovery.derive_discovery_scope(db_session, agent.id).version
    assert job.scope_version == expected
    assert _request(published)["scope_version"] == expected


async def test_the_request_serializes_its_datetimes_as_isoformat(
    db_session, factories, online, published
):
    """`publish_agent_control_frame` dumps with `json.dumps(default=str)`, which
    renders a datetime as "2026-08-08 18:00:00+00:00" — a space separator Go's
    `time.Time` rejects outright. The same hazard `monitor_probe_dispatch`
    documents at its own `scheduled_at`/`deadline_at`."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    await agent_discovery.dispatch_discovery_job(db_session, job.id)

    deadline = _request(published)["deadline_at"]
    assert isinstance(deadline, str)
    assert " " not in deadline
    assert "T" in deadline
    # And the whole payload still satisfies the contract both languages share.
    DiscoveryRequestPayload.model_validate(_request(published))


async def test_the_request_carries_the_jobs_targets_and_the_grants_bounds(
    db_session, factories, online, published
):
    agent = _agent(
        db_session,
        factories,
        config={"max_concurrent_hosts": 8, "host_timeout_ms": 900, "tcp_ports": [22, 443]},
    )
    job = _job(db_session, agent)

    await agent_discovery.dispatch_discovery_job(db_session, job.id)

    payload = _request(published)
    assert payload["targets"] == [_SUBNET]
    assert payload["tcp_ports"] == [22, 443]
    assert payload["max_concurrent_hosts"] == 8
    assert payload["host_timeout_ms"] == 900
    assert payload["methods"] == list(agent_discovery.DISCOVERY_METHODS)


async def test_a_job_that_names_its_own_ports_ships_those_and_not_the_whole_grant(
    db_session, factories, online, published
):
    """An operator who asked for two ports gets two, not the nine the grant
    would allow. The narrower set is still a subset of the grant, which is what
    Task 19 and the dispatch-time re-check both prove."""
    agent = _agent(db_session, factories)
    job = _job(
        db_session, agent, label=f"{discovery_service._NMAP_OVERRIDE_PREFIX}-p 22,443 --open"
    )

    await agent_discovery.dispatch_discovery_job(db_session, job.id)

    assert _request(published)["tcp_ports"] == [22, 443]


async def test_a_dispatched_job_is_not_dispatched_twice(db_session, factories, online, published):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is True
    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    assert len([f for _, f in published if f["type"] == TYPE_DISCOVERY_REQUEST]) == 1


async def test_an_undeliverable_request_closes_the_job_as_dispatch_failed(
    db_session, factories, online, undeliverable
):
    """`publish_agent_control_frame` returning False means Redis itself was
    unavailable, so nothing can have arrived — the job has to close rather than
    sit on a lease no agent ever received."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_DISPATCH_FAILED


# ── D-5: an offline agent parks the job and holds no slot ─────────────────────


def test_the_dispatch_deadline_is_named_and_defaults_to_fifteen_minutes() -> None:
    """D-5's number, pinned to its magnitude rather than to itself. Task 23
    derives its expiry pass from this constant."""
    assert agent_discovery.DISPATCH_DEADLINE_S == 900


async def test_an_offline_agent_releases_the_claim_and_publishes_nothing(
    db_session, factories, offline, published
):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "queued"
    assert job.progress_phase == agent_discovery.PHASE_WAITING_FOR_AGENT
    assert job.dispatch_status == agent_discovery.DISPATCH_STATUS_QUEUED
    assert job.dispatch_deadline_at is not None
    assert job.dispatch_deadline_at > utcnow() + timedelta(
        seconds=agent_discovery.DISPATCH_DEADLINE_S - 60
    )
    # Nothing was published, and no token exists that a finding could quote.
    assert published == []
    assert job.dispatch_id is None


async def test_a_job_waiting_for_an_agent_consumes_no_concurrency_slot(
    db_session, factories, offline, published
):
    """`discovery_scheduler._running_scan_count` counts `status == "running"`.
    A job left running while it waits for an agent would starve every other
    scan for the whole 15-minute deadline while doing no work at all."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    await agent_discovery.dispatch_discovery_job(db_session, job.id)

    db_session.refresh(job)
    assert discovery_scheduler._running_scan_count(db_session) == 0


async def test_an_agent_with_no_link_owner_also_parks_the_job(
    db_session, factories, published, monkeypatch
):
    """Presence and connection ownership expire together but are written by
    different call sites; only the owner proves some worker can deliver."""
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=True))
    monkeypatch.setattr(agent_registry, "get_agent_connection_owner", AsyncMock(return_value=None))
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert (job.status, job.progress_phase) == ("queued", agent_discovery.PHASE_WAITING_FOR_AGENT)
    assert published == []


# ── The live re-check, in addition to the creation-time one ───────────────────


async def test_a_scope_that_no_longer_covers_the_target_fails_the_job_at_dispatch(
    db_session, factories, online, published
):
    """The concrete reason the re-check exists: scope is derived from what the
    agent reports about its own interfaces, so a job validated at creation can
    be out of scope by the time it is dispatched."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    row = db_session.query(AgentNetwork).filter(AgentNetwork.agent_id == agent.id).one()
    row.facts = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["192.168.7.5/24"]}]
    row.generation += 1
    db_session.flush()

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
    assert published == []


async def test_a_capability_revoked_after_creation_fails_the_job_at_dispatch(
    db_session, factories, online, published
):
    from app.db.models import AgentCapabilityGrant

    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="local_discovery")
        .one()
    )
    grant.enabled = False
    db_session.flush()

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_CAPABILITY_DISABLED
    assert published == []


async def test_an_inactive_agent_fails_the_job_at_dispatch(
    db_session, factories, online, published
):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    agent.status = "revoked"
    db_session.flush()

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_AGENT_UNAVAILABLE
    assert published == []


async def test_a_port_the_grant_no_longer_allows_fails_the_job_at_dispatch(
    db_session, factories, online, published
):
    """Ports are re-validated too, not just targets: an administrator can
    narrow `tcp_ports` between a profile save and the job it produces."""
    agent = _agent(db_session, factories, config={"tcp_ports": [22]})
    job = _job(
        db_session, agent, label=f"{discovery_service._NMAP_OVERRIDE_PREFIX}-p 22,9999 --open"
    )

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_DISPATCH_FAILED
    assert discovery_service.REASON_PORT_NOT_GRANTED in (job.error_text or "")
    assert published == []


async def test_a_target_over_the_live_address_ceiling_fails_the_job_at_dispatch(
    db_session, factories, online, published
):
    agent = _agent(
        db_session,
        factories,
        config={"max_addresses_per_job": 64},
        facts=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.60.0.5/24"]}],
    )
    job = _job(db_session, agent)

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_reason == agent_discovery.ERROR_DISPATCH_FAILED
    assert discovery_service.REASON_ADDRESS_LIMIT in (job.error_text or "")
    assert published == []


# ── Two real sessions ─────────────────────────────────────────────────────────


@contextlib.contextmanager
def _committed_agent_job(**job_kwargs):  # type: ignore[no-untyped-def]
    """One queued agent job on its own connection, cleaned up afterwards."""
    from app.db.session import SessionLocal
    from tests.factories import Factories

    with SessionLocal() as setup:
        tenant = Tenant(name=f"discovery-race-{secrets.token_hex(4)}")
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


def test_two_real_sessions_cannot_double_dispatch_one_job(setup_db, monkeypatch) -> None:
    """Only two real connections prove the claim is a compare-and-set.

    Driven sequentially the same assertion passes against a read-modify-write:
    both readers see `dispatch_status IS NULL`, both write `dispatched`, and the
    agent receives two `discovery.request` frames for one job — two sweeps, two
    terminal summaries, and a second dispatch token whose findings the first
    summary's finalization would reject at random.

    The lease lives on the job row rather than on a row of its own, so there is
    no partial unique index to catch this (see `db/models.py`'s note on
    `uq_scan_jobs_dispatch_id`): the rowcount check is the whole mechanism, and
    it is what this races.

    The barrier is installed *inside* the dispatcher rather than around it, at
    the scope derivation that runs after the cheap "is this job still queued"
    read and before the claim. Barriering the call itself is not enough and was
    observed not to be: the first thread routinely finishes the whole dispatch
    before the second issues its first SELECT, and the test then passes on the
    pre-check while the compare-and-set goes entirely unexercised.
    """
    from app.db.session import SessionLocal

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
    monkeypatch.setattr(agent_registry, "is_agent_online", AsyncMock(return_value=True))
    monkeypatch.setattr(
        agent_registry, "get_agent_connection_owner", AsyncMock(return_value="worker-1")
    )

    with _committed_agent_job() as (_agent_id, job_id, _tenant_id):

        def _dispatch(_n: int) -> bool:
            with SessionLocal() as session:
                return asyncio.run(agent_discovery.dispatch_discovery_job(session, job_id))

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(_dispatch, [0, 1]))

        assert sorted(outcomes) == [False, True], outcomes
        requests = [f for f in frames if f["type"] == TYPE_DISCOVERY_REQUEST]
        assert len(requests) == 1, requests

        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.dispatch_status == agent_discovery.DISPATCH_STATUS_DISPATCHED
            assert stored.status == "running"
            assert stored.dispatch_id == requests[0]["payload"]["dispatch_id"]


def test_a_duplicated_dispatch_token_is_refused_by_the_unique_index(setup_db) -> None:
    """The second half of the backstop. The compare-and-set stops two workers
    racing one job; `uq_scan_jobs_dispatch_id` stops a replayed or duplicated
    token from ever addressing two jobs at once — which is what would let one
    agent's finding be written against another job's lease.

    Written on a real connection because the index is a database object; the
    partial predicate (`dispatch_id IS NOT NULL`) is exercised too, since every
    server job ever written carries a NULL there.
    """
    from app.db.session import SessionLocal

    token = secrets.token_hex(16)
    with _committed_agent_job(dispatch_id=token, dispatch_status="dispatched") as (
        agent_id,
        _job_id,
        tenant_id,
    ):
        with SessionLocal() as second:
            second.add(
                ScanJob(
                    scan_agent_id=agent_id,
                    dispatch_id=token,
                    dispatch_status="dispatched",
                    target_cidr=_SUBNET,
                    status="running",
                    scan_types_json='["agent_connect"]',
                    source_type="agent",
                    tenant_id=tenant_id,
                    created_at=utcnow_iso(),
                )
            )
            with pytest.raises(IntegrityError) as excinfo:
                second.commit()
            assert "uq_scan_jobs_dispatch_id" in str(excinfo.value)
            second.rollback()

        # And two NULLs do not collide, which is what the partial predicate buys.
        with SessionLocal() as nulls:
            for _ in range(2):
                nulls.add(
                    ScanJob(
                        target_cidr=_SUBNET,
                        status="queued",
                        scan_types_json='["nmap"]',
                        created_at=utcnow_iso(),
                    )
                )
            nulls.commit()
            ids = [
                row[0]
                for row in nulls.query(ScanJob.id)
                .filter(ScanJob.dispatch_id.is_(None), ScanJob.target_cidr == _SUBNET)
                .all()
            ]
            nulls.execute(delete(ScanJob).where(ScanJob.id.in_(ids)))
            nulls.commit()


# ── The lease survives the awaits, or the dispatcher gives it up ──────────────
# Everything between `_claim` and the publish awaits: `evaluate_eligibility` is a
# real Redis round trip and therefore a real suspension point. A cancellation
# committed by another connection in that window is invisible to a dispatcher
# holding an ORM object it loaded beforehand, so both writes on the far side of
# the await are compare-and-sets against the token `_claim` minted, and only two
# real connections can prove it.


@contextlib.contextmanager
def _cancelled_during(monkeypatch, job_id: int, decision):  # type: ignore[no-untyped-def]
    """Take *job_id* terminal on another connection, from inside the await.

    The interleaving is installed at `evaluate_eligibility` because that is the
    real suspension point in `dispatch_discovery_job`: the claim has committed,
    the publish has not, and the dispatcher is holding a job row it read before
    any of it. Committed on its own session because a cancellation this one
    could see without committing would prove nothing about the guard.
    """
    from app.db.session import SessionLocal

    async def cancel_then_answer(db, agent_id, **kwargs):  # type: ignore[no-untyped-def]
        with SessionLocal() as operator:
            operator.execute(
                update(ScanJob)
                .where(ScanJob.id == job_id)
                .values(
                    status="cancelled",
                    dispatch_status=agent_discovery.DISPATCH_STATUS_CANCELLED,
                    completed_at=utcnow_iso(),
                    progress_phase="cancelled",
                )
            )
            operator.commit()
        return decision

    monkeypatch.setattr(discovery_eligibility, "evaluate_eligibility", cancel_then_answer)
    yield


def test_a_job_cancelled_while_its_dispatcher_waits_is_not_resurrected(
    setup_db, monkeypatch
) -> None:
    """D-5 parks a job for an offline agent — but only a job it still owns.

    `_release_to_waiting` writes `queued` + `waiting_for_agent`, which is the one
    state on this path that is *not* terminal, so a blind write here does not
    merely lose an outcome: it reopens a job an operator already cancelled and
    hands it back to the scheduler to dispatch again. The claim commits, the
    dispatcher awaits Redis, the cancellation commits, and the dispatcher
    resumes holding a row that no longer exists in the form it read it.
    """
    from app.db.session import SessionLocal

    offline_now = discovery_eligibility.Eligibility(
        ok=False, reason=discovery_eligibility.REASON_AGENT_OFFLINE
    )

    with _committed_agent_job() as (_agent_id, job_id, _tenant_id):
        with _cancelled_during(monkeypatch, job_id, offline_now), SessionLocal() as session:
            assert asyncio.run(agent_discovery.dispatch_discovery_job(session, job_id)) is False

        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.status == "cancelled"
            assert stored.dispatch_status == agent_discovery.DISPATCH_STATUS_CANCELLED
            assert stored.progress_phase != agent_discovery.PHASE_WAITING_FOR_AGENT
            # The lease is left exactly as the cancellation left it. Clearing it
            # is `_release_to_waiting`'s signature write, so a token still on the
            # row is the proof that no part of that write landed.
            assert _DISPATCH_ID_RE.fullmatch(stored.dispatch_id or "")


def test_a_job_cancelled_before_the_publish_never_receives_a_request(setup_db, monkeypatch) -> None:
    """`discovery.cancel` goes out when the row closes; the request must not
    follow it.

    Nothing between the claim and the publish re-read the job, so a cancellation
    landing in the await window delivered the two frames in the wrong order: the
    agent abandons a dispatch it has not been given, then starts sweeping the
    network for it, and every finding it produces is refused on arrival.
    """
    from app.db.session import SessionLocal

    frames: list[dict] = []

    async def spy(agent_id: int, frame: dict) -> bool:
        frames.append(frame)
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=spy))

    with _committed_agent_job() as (_agent_id, job_id, _tenant_id):
        with (
            _cancelled_during(monkeypatch, job_id, discovery_eligibility.Eligibility(ok=True)),
            SessionLocal() as session,
        ):
            assert asyncio.run(agent_discovery.dispatch_discovery_job(session, job_id)) is False

        assert [f for f in frames if f["type"] == TYPE_DISCOVERY_REQUEST] == []
        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.status == "cancelled"
            assert stored.dispatch_status == agent_discovery.DISPATCH_STATUS_CANCELLED


def test_cancelling_never_overwrites_a_job_that_finished_first(setup_db, monkeypatch) -> None:
    """`finalize_agent_job` is a compare-and-set; the cancellation triggers have
    to be the same one or they undo it.

    `_open_agent_jobs` SELECTs and the caller writes, and in between the agent's
    terminal summary can be accepted on the `/link` connection. A blind write
    then turns a scan that *completed* into one that was cancelled and emits a
    `discovery.cancel` for work that already finished — plus a `job_update`
    telling every client the same untruth.
    """
    from app.db.session import SessionLocal

    with _committed_agent_job(
        status="running",
        dispatch_status=agent_discovery.DISPATCH_STATUS_DISPATCHED,
        dispatch_id=secrets.token_hex(16),
    ) as (agent_id, job_id, _tenant_id):
        open_jobs = agent_discovery._open_agent_jobs

        def racing_open_jobs(db, **kwargs):  # type: ignore[no-untyped-def]
            jobs = open_jobs(db, **kwargs)
            with SessionLocal() as link:
                link.execute(
                    update(ScanJob)
                    .where(ScanJob.id == job_id)
                    .values(
                        status="completed",
                        dispatch_status=agent_discovery.DISPATCH_STATUS_COMPLETED,
                        completed_at=utcnow_iso(),
                        progress_phase="done",
                    )
                )
                link.commit()
            return jobs

        monkeypatch.setattr(agent_discovery, "_open_agent_jobs", racing_open_jobs)

        with SessionLocal() as session:
            cancellation = agent_discovery.cancel_agent_dispatches(
                session, agent_id, reason=agent_discovery.ERROR_CAPABILITY_DISABLED
            )
            session.commit()

        assert cancellation.cancels == []
        assert cancellation.job_updates == []
        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.status == "completed"
            assert stored.dispatch_status == agent_discovery.DISPATCH_STATUS_COMPLETED
            assert stored.error_reason is None


# ── Cardinality, before the lease ─────────────────────────────────────────────


async def test_a_job_naming_more_targets_than_one_request_can_carry_claims_no_lease(
    db_session, factories, online, published
):
    """`DiscoveryRequestPayload.targets` is capped at `MAX_DISCOVERY_TARGETS`
    (plan §4) and `_discovery_request_frame` validates against that model — but
    it runs after `_claim` has committed, so an over-cardinality job used to take
    a lease and then die on a pydantic error with the row left `running` and a
    dispatch token nobody would ever close. `target_cidr` is an editable column,
    so the creation-time check in `validate_agent_execution_location` is not the
    last word on it.
    """
    agent = _agent(db_session, factories)
    too_many = ",".join(f"10.60.0.{octet}/32" for octet in range(1, MAX_DISCOVERY_TARGETS + 2))
    job = _job(db_session, agent, target_cidr=too_many)
    assert len(too_many.split(",")) == MAX_DISCOVERY_TARGETS + 1

    assert await agent_discovery.dispatch_discovery_job(db_session, job.id) is False

    db_session.expire_all()
    stored = db_session.get(ScanJob, job.id)
    assert stored.status == "failed"
    assert stored.error_reason == agent_discovery.ERROR_DISPATCH_FAILED
    assert agent_discovery.REASON_TARGET_LIMIT in (stored.error_text or "")
    # No lease was ever minted, so there is no dispatch for a finding to quote
    # and nothing for the reconciler to expire.
    assert stored.dispatch_id is None
    assert stored.dispatch_status != agent_discovery.DISPATCH_STATUS_DISPATCHED
    assert published == []
