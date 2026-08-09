"""Slice 4 Phase D / Task 24: the zero-configuration discovery bootstrap.

Plan §2 and §3 promise that an operator installs the agent, approves it with
normal defaults, and discovery of its local networks just starts — no CIDR
entry, no profile, no port list, no agent-side configuration. This file is what
that promise is made of, so every test below is named after the invariant it
pins rather than the function it calls.

Four of them carry more weight than the rest:

* **A user profile targeting the same CIDR is never touched.** Plan §3 is
  explicit that "user-created profiles remain separate and are never
  overwritten", and D-7's partial unique index exists precisely so both rows can
  coexist. This is the failure an operator would feel hardest — their hand-tuned
  profile silently retuned, or cancelled, by an automatic pass.
* **An admin edit outlives the next report.** D-7: the derived
  `f"{agent_id % 60} */6 * * *"` cadence is for a *brand-new* profile only. Re-
  deriving it on every pass would revert plan §6's "edit cadence and scan depth"
  the moment a readiness frame arrived, which is at most fifteen minutes later.
* **A subnet that disappears disables rather than deletes**, and cancels what it
  had in flight through the entry point D-14 names (`profile_disabled`), because
  once the profile is off nothing else will ever close those jobs.
* **The trigger fires on a report's *presence*, not on a change.** The first
  hello after approval carries networks but no collector readiness yet, so the
  bootstrap is refused; the readiness frame that makes the agent eligible often
  reports the *same* interfaces. A change-gated trigger would therefore never
  fire again, and zero-configuration would silently require a network change
  that may never come.

`db_session` is SAVEPOINT-isolated, so the `db.commit()` calls inside
`discovery_profiles_service` and `discovery_service.create_scan_job` are
savepoint releases and roll back with the test.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core import agent_scope
from app.core.time import utcnow_iso
from app.db.models import DiscoveryProfile, ScanJob, ScanResult
from app.schemas.agent_frame import HelloPayload, NetworkFacts
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services import (
    agent_registry,
    agent_telemetry,
    discovery_bootstrap,
    discovery_profiles_service,
    discovery_service,
)

ACTOR = "test-admin"

# One safe, directly connected RFC 1918 /24 — 256 addresses, comfortably inside
# the 1024-address default ceiling — and a second on a different private block,
# so "one profile per subnet" is distinguishable from "one profile".
_SAFE = "10.60.0.0/24"
_SAFE_ADDR = "10.60.0.5/24"
_SECOND = "192.168.9.0/24"
_SECOND_ADDR = "192.168.9.5/24"


def _iface(name: str, addrs: list[str], flags: tuple[str, ...] = ("broadcast", "up")) -> dict:
    """One `agent_networks.facts` entry in the normalized form
    `record_network_facts` stores — sorted flags, sorted addresses."""
    return {"name": name, "flags": sorted(flags), "addrs": sorted(addrs)}


_DEFAULT_FACTS = [_iface("eth0", [_SAFE_ADDR])]
_BOTH_FACTS = [_iface("eth0", [_SAFE_ADDR]), _iface("eth1", [_SECOND_ADDR])]


def _agent(db_session, factories, *, facts=None, config=None, readiness="ready", status="active"):  # type: ignore[no-untyped-def]
    """An agent that has just been approved and has reported for the first time.

    Every §3 precondition is satisfied so the tests below can remove exactly one
    at a time: active status, an enabled `local_discovery` grant, a reported
    network, and a fresh `discovery.tcp` readiness row.
    """
    agent = factories.agent(status=status)
    factories.agent_capability_grant(
        agent, capability="local_discovery", enabled=True, config=config or {}
    )
    factories.agent_network(agent, facts=_DEFAULT_FACTS if facts is None else facts)
    if readiness is not None:
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state=readiness)
    db_session.flush()
    return agent


def _reported(db_session, agent, facts) -> None:  # type: ignore[no-untyped-def]
    """Replace the agent's stored network report, as a later frame would."""
    row = agent_registry_network_row(db_session, agent.id)
    row.facts = facts
    row.generation += 1
    db_session.flush()


def agent_registry_network_row(db_session, agent_id: int):  # type: ignore[no-untyped-def]
    from app.db.models import AgentNetwork

    return (
        db_session.execute(select(AgentNetwork).where(AgentNetwork.agent_id == agent_id))
        .scalars()
        .one()
    )


def _system_profiles(db_session, agent_id: int) -> list[DiscoveryProfile]:
    return list(
        db_session.execute(
            select(DiscoveryProfile)
            .where(
                DiscoveryProfile.scan_agent_id == agent_id,
                DiscoveryProfile.managed_by == discovery_bootstrap.MANAGED_BY_SYSTEM,
            )
            .order_by(DiscoveryProfile.normalized_cidr)
        )
        .scalars()
        .all()
    )


def _jobs(db_session, agent_id: int) -> list[ScanJob]:
    return list(
        db_session.execute(
            select(ScanJob).where(ScanJob.scan_agent_id == agent_id).order_by(ScanJob.id)
        )
        .scalars()
        .all()
    )


@pytest.fixture(autouse=True)
def deferred_starts(monkeypatch):  # type: ignore[no-untyped-def]
    """Capture the delayed scan starts instead of arming real loop timers.

    Autouse because a stray `call_later` outlives the test that armed it. The
    real callable is handed back so the one test that is *about* the deferral
    can still exercise it.
    """
    real = discovery_bootstrap._start_after_delay
    calls: list[tuple[int, float]] = []
    monkeypatch.setattr(
        discovery_bootstrap,
        "_start_after_delay",
        lambda job_id, delay_s: calls.append((job_id, delay_s)),
    )
    return SimpleNamespace(calls=calls, real=real)


@pytest.fixture(autouse=True)
def inert_control_frames(monkeypatch):  # type: ignore[no-untyped-def]
    """The `discovery.cancel` frames a disappearing subnet produces. Published
    after the profile service commits, so they must not reach Redis here."""
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(return_value=True))


@pytest.fixture(autouse=True)
def discovery_jobs():  # type: ignore[no-untyped-def]
    """APScheduler is process-global state: `create_profile` registers a cron job
    for every profile the bootstrap creates, and it would outlive the rolled-back
    row it names."""
    from app.core.scheduler import get_scheduler

    yield
    for job in get_scheduler().get_jobs():
        if job.id.startswith("discovery_profile_"):
            job.remove()


# ── The safe baseline ─────────────────────────────────────────────────────────


async def test_first_report_creates_one_enabled_system_profile_per_safe_subnet(
    db_session, factories
):
    agent = _agent(db_session, factories, facts=_BOTH_FACTS)

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    profiles = _system_profiles(db_session, agent.id)
    assert [p.normalized_cidr for p in profiles] == [_SAFE, _SECOND]
    assert sorted(outcome.created_profile_ids) == sorted(p.id for p in profiles)
    for profile in profiles:
        assert profile.enabled == 1
        assert profile.scan_agent_id == agent.id
        assert profile.managed_by == "system"
        assert json.loads(profile.scan_types) == ["agent_connect"]
        # D-7: the derived per-agent minute is the cadence jitter primitive —
        # cron is the only cadence field the table has.
        assert profile.schedule_cron == f"{agent.id % 60} */6 * * *"


async def test_no_cidr_or_agent_side_configuration_is_required(db_session, factories):
    """Plan §10: the operator supplies nothing. The profile's target comes from
    what the agent reported about its own interfaces and nothing else."""
    agent = _agent(db_session, factories)

    await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    (profile,) = _system_profiles(db_session, agent.id)
    assert profile.cidr == _SAFE
    assert profile.nmap_arguments is None


@pytest.mark.parametrize(
    "description,unsafe,config",
    [
        ("loopback", _iface("lo", ["127.0.0.1/8"], flags=("loopback", "up")), None),
        ("link-local", _iface("eth9", ["169.254.10.5/16"]), None),
        ("default route", _iface("eth9", ["0.0.0.0/0"]), None),
        ("tunnel", _iface("tun0", ["10.8.0.2/24"], flags=("pointtopoint", "up")), None),
        ("public", _iface("eth9", ["203.0.113.5/24"]), None),
        ("over-wide prefix", _iface("eth9", ["10.0.0.5/8"]), None),
        # MIN_SCOPE_PREFIX_V4 = 16 admits a /16, so the only thing that can
        # refuse it is the grant's own address ceiling: 65 536 > 4 096.
        (
            "over the address ceiling",
            _iface("eth9", ["172.20.0.5/16"]),
            {"max_addresses_per_job": 4096},
        ),
        # Plan §2/§6: an administrator can centrally exclude a detected subnet.
        # It is still directly connected and still private, so `derive_scope`
        # reports it — only `network_in_scope` subtracts it.
        (
            "centrally excluded",
            _iface("eth9", ["10.61.0.5/24"]),
            {"excluded_cidrs": ["10.61.0.0/24"]},
        ),
    ],
)
async def test_unsafe_or_unbounded_subnets_never_become_system_profiles(
    db_session, factories, caplog, description, unsafe, config
):
    agent = _agent(
        db_session, factories, facts=[_iface("eth0", [_SAFE_ADDR]), unsafe], config=config
    )

    with caplog.at_level(logging.WARNING):
        await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    profiles = _system_profiles(db_session, agent.id)
    assert [p.normalized_cidr for p in profiles] == [_SAFE], (
        f"{description} was admitted to automatic scope"
    )
    # Excluded by *policy*, not by a write that raised and was contained. The
    # profile service refuses an out-of-scope target too, so the row assertion
    # above passes either way; only this one tells the two apart.
    contained = [
        r
        for r in caplog.records
        if r.name == "app.services.discovery_bootstrap" and r.levelno >= logging.WARNING
    ]
    assert contained == [], f"{description} was refused by a failed write, not by scope"


def test_eligible_subnets_refuses_a_subnet_larger_than_the_job_ceiling():
    """The one judgement this module adds to the shared evaluator.

    `MIN_SCOPE_PREFIX_V4 = 16` admits a /16, so nothing in `agent_scope` refuses
    65 536 addresses — only the grant's `max_addresses_per_job` does.
    """
    scope = agent_scope.derive_scope([_iface("eth0", ["172.20.0.5/16"])], {})

    assert discovery_bootstrap.eligible_subnets(scope, address_ceiling=4096) == []
    assert discovery_bootstrap.eligible_subnets(scope, address_ceiling=65_536) == ["172.20.0.0/16"]


def test_eligible_subnets_refuses_a_prefix_wider_than_the_scope_ceiling():
    """`MIN_SCOPE_PREFIX_V4` and the address ceiling are different rules.

    On IPv4 they usually agree — the widest admissible prefix already holds
    sixteen times the largest grantable ceiling — so this hands
    `eligible_subnets` a ceiling big enough that only the width rule can refuse,
    or a mutant that dropped `network_in_scope` entirely would still pass.
    """
    scope = agent_scope.derive_scope([_iface("eth0", ["10.0.0.5/8"])], {})

    assert scope.direct_networks == ("10.0.0.0/8",)
    assert discovery_bootstrap.eligible_subnets(scope, address_ceiling=2**25) == []


def test_eligible_subnets_ignores_an_administrators_routed_overrides():
    """`additional_cidrs` are routed networks an administrator added deliberately.

    They are in scope and they are *not* automatic: plan §3 step 6 is about a
    subnet appearing on and disappearing from the agent's own interfaces, and an
    automatic profile for an override would be this module inventing intent.
    """
    scope = agent_scope.derive_scope(
        [_iface("eth0", [_SAFE_ADDR])], {"additional_cidrs": ["10.99.0.0/24"]}
    )

    assert "10.99.0.0/24" in scope.networks
    assert discovery_bootstrap.eligible_subnets(scope, address_ceiling=1024) == [_SAFE]


# ── Idempotency ───────────────────────────────────────────────────────────────


async def test_repeated_reports_create_no_duplicate_profile_and_no_duplicate_scan(
    db_session, factories, deferred_starts
):
    agent = _agent(db_session, factories)

    first = await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    second = await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    third = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert len(_system_profiles(db_session, agent.id)) == 1
    assert len(_jobs(db_session, agent.id)) == 1
    assert len(first.created_profile_ids) == 1
    assert second.created_profile_ids == () and third.created_profile_ids == ()
    assert second.queued_job_ids == () and third.queued_job_ids == ()
    assert len(deferred_starts.calls) == 1


# ── The initial scan ──────────────────────────────────────────────────────────


async def test_the_initial_scan_is_queued_after_a_bounded_jitter(
    db_session, factories, deferred_starts
):
    agent = _agent(db_session, factories)

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    (job_id,) = outcome.queued_job_ids
    job = db_session.get(ScanJob, job_id)
    assert job.status == "queued"
    assert job.scan_agent_id == agent.id
    assert job.target_cidr == _SAFE
    assert json.loads(job.scan_types_json) == ["agent_connect"]
    # Nothing was started inline: the report path must not run a scan.
    assert [call[0] for call in deferred_starts.calls] == [job_id]
    delay = deferred_starts.calls[0][1]
    assert delay == discovery_bootstrap.initial_scan_delay_s(agent.id)
    floor = discovery_bootstrap.INITIAL_SCAN_JITTER_FLOOR_S
    assert floor <= delay < floor + discovery_bootstrap.INITIAL_SCAN_JITTER_SPREAD_S


def test_the_initial_scan_delay_is_bounded_and_actually_spreads():
    floor = discovery_bootstrap.INITIAL_SCAN_JITTER_FLOOR_S
    spread = discovery_bootstrap.INITIAL_SCAN_JITTER_SPREAD_S
    delays = [discovery_bootstrap.initial_scan_delay_s(agent_id) for agent_id in range(1, 400)]
    assert all(floor <= d < floor + spread for d in delays)
    # A constant would satisfy "bounded" and spread nothing, which is the whole
    # point of the jitter: a fleet reconnecting together must not dispatch
    # together.
    assert len(set(delays[:60])) == 60


async def test_start_after_delay_defers_the_scan_off_the_reporting_path(
    monkeypatch, deferred_starts
):
    started: list[int] = []
    monkeypatch.setattr(
        discovery_service, "schedule_discovery_scan_job", lambda job_id: started.append(job_id)
    )

    deferred_starts.real(4242, 0)

    assert started == [], "the scan started inline, on the frame-handling path"
    await asyncio.sleep(0.05)
    assert started == [4242]


# ── Disappearance ─────────────────────────────────────────────────────────────


async def test_a_disappearing_subnet_is_disabled_cancels_its_job_and_retains_history(
    db_session, factories
):
    agent = _agent(db_session, factories, facts=_BOTH_FACTS)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    gone = next(p for p in _system_profiles(db_session, agent.id) if p.normalized_cidr == _SECOND)
    in_flight = next(j for j in _jobs(db_session, agent.id) if j.profile_id == gone.id)
    db_session.add(
        ScanResult(
            scan_job_id=in_flight.id,
            ip_address="192.168.9.31",
            source_type="agent",
            created_at=utcnow_iso(),
        )
    )
    db_session.flush()

    _reported(db_session, agent, [_iface("eth0", [_SAFE_ADDR])])
    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    db_session.refresh(gone)
    assert outcome.disabled_profile_ids == (gone.id,)
    assert gone.enabled == 0
    # Disabled, never deleted: the row and everything hanging off it is history.
    assert db_session.get(DiscoveryProfile, gone.id) is not None
    db_session.refresh(in_flight)
    assert in_flight.status == "cancelled"
    assert in_flight.error_reason == "profile_disabled"
    retained = (
        db_session.execute(select(ScanResult).where(ScanResult.scan_job_id == in_flight.id))
        .scalars()
        .all()
    )
    assert [r.ip_address for r in retained] == ["192.168.9.31"]
    # The surviving subnet is untouched.
    still = next(p for p in _system_profiles(db_session, agent.id) if p.normalized_cidr == _SAFE)
    assert still.enabled == 1


async def test_a_subnet_that_comes_back_is_re_enabled_and_re_scanned(db_session, factories):
    agent = _agent(db_session, factories, facts=_BOTH_FACTS)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    gone = next(p for p in _system_profiles(db_session, agent.id) if p.normalized_cidr == _SECOND)
    _reported(db_session, agent, [_iface("eth0", [_SAFE_ADDR])])
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    _reported(db_session, agent, _BOTH_FACTS)
    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    db_session.refresh(gone)
    assert gone.enabled == 1
    # Re-enabled, not re-created: the history on the original row is the point.
    assert outcome.created_profile_ids == ()
    assert outcome.reenabled_profile_ids == (gone.id,)
    assert len(_system_profiles(db_session, agent.id)) == 2
    assert len(outcome.queued_job_ids) == 1


# ── The user's own profiles ───────────────────────────────────────────────────


async def test_a_user_profile_on_the_same_cidr_is_never_touched(db_session, factories):
    agent = _agent(db_session, factories)
    mine = discovery_profiles_service.create_profile(
        db_session,
        DiscoveryProfileCreate(
            name="my hand-tuned sweep",
            cidr=_SAFE,
            scan_types=["agent_connect"],
            scan_agent_id=agent.id,
            schedule_cron="13 2 * * *",
        ),
        ACTOR,
    )
    mine_job = ScanJob(
        scan_agent_id=agent.id,
        profile_id=mine.id,
        target_cidr=_SAFE,
        status="running",
        scan_types_json='["agent_connect"]',
        source_type="agent",
        created_at=utcnow_iso(),
    )
    db_session.add(mine_job)
    db_session.flush()
    before = (mine.name, mine.enabled, mine.schedule_cron, mine.updated_at, mine.managed_by)

    # The subnet appears...
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    # ...and then goes away again, which is the pass that disables profiles.
    _reported(db_session, agent, [_iface("eth0", ["10.61.0.5/24"])])
    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    db_session.refresh(mine)
    assert (mine.name, mine.enabled, mine.schedule_cron, mine.updated_at, mine.managed_by) == before
    assert mine.id not in outcome.disabled_profile_ids
    db_session.refresh(mine_job)
    assert mine_job.status == "running", "a user profile's in-flight job was cancelled"


# ── Administrator edits ───────────────────────────────────────────────────────


async def test_an_admin_edited_cadence_and_depth_survive_the_next_report(db_session, factories):
    agent = _agent(db_session, factories)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (profile,) = _system_profiles(db_session, agent.id)
    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate(
            {"schedule_cron": "17 3 * * *", "nmap_arguments": "-p 22,443"}
        ),
        ACTOR,
    )

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    db_session.refresh(profile)
    assert outcome.created_profile_ids == ()
    assert profile.schedule_cron == "17 3 * * *"
    assert profile.nmap_arguments == "-p 22,443"
    assert json.loads(profile.scan_types) == ["agent_connect"]
    assert profile.managed_by == "system", "the profile stopped being upsertable"


# ── When the bootstrap must not run ───────────────────────────────────────────


async def test_the_bootstrap_waits_for_collector_readiness_and_then_runs(db_session, factories):
    """The hello that carries networks arrives before any readiness row exists.

    This is why the trigger cannot be change-gated: the readiness frame that
    makes the agent eligible usually reports the *same* interfaces.
    """
    agent = _agent(db_session, factories, readiness=None)

    early = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert early.skipped_reason == "readiness_unknown"
    assert _system_profiles(db_session, agent.id) == []

    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    db_session.flush()
    later = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert later.skipped_reason is None
    assert len(_system_profiles(db_session, agent.id)) == 1


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"status": "pending"}, "agent_inactive"),
        ({"status": "revoked"}, "agent_inactive"),
        ({"readiness": "degraded"}, "readiness_degraded"),
    ],
)
async def test_an_ineligible_agent_gets_no_automatic_profiles(
    db_session, factories, kwargs, reason
):
    agent = _agent(db_session, factories, **kwargs)

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert outcome.skipped_reason == reason
    assert _system_profiles(db_session, agent.id) == []


async def test_an_agent_without_the_local_discovery_grant_gets_no_profiles(db_session, factories):
    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=_DEFAULT_FACTS)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    db_session.flush()

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert outcome.skipped_reason == "capability_disabled"
    assert _system_profiles(db_session, agent.id) == []


async def test_one_unusable_subnet_does_not_strand_the_others(db_session, factories, monkeypatch):
    agent = _agent(db_session, factories, facts=_BOTH_FACTS)
    real = discovery_profiles_service.create_profile

    def flaky(db, payload, actor, **kwargs):  # type: ignore[no-untyped-def]
        if payload.cidr == _SAFE:
            raise ValueError("this subnet cannot be saved")
        return real(db, payload, actor, **kwargs)

    monkeypatch.setattr(discovery_profiles_service, "create_profile", flaky)

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert [p.normalized_cidr for p in _system_profiles(db_session, agent.id)] == [_SECOND]
    assert len(outcome.created_profile_ids) == 1


# ── The trigger ───────────────────────────────────────────────────────────────


@pytest.fixture
def fired(monkeypatch):  # type: ignore[no-untyped-def]
    agent_ids: list[int] = []

    def spy(agent_id: int) -> bool:
        agent_ids.append(agent_id)
        return True

    monkeypatch.setattr(discovery_bootstrap, "schedule_bootstrap", spy)
    return agent_ids


def test_a_networks_report_fires_the_trigger_on_presence_not_on_change(
    db_session, factories, fired
):
    agent = _agent(db_session, factories)
    facts = [NetworkFacts(name="eth0", flags=["broadcast", "up"], addrs=[_SAFE_ADDR])]

    agent_registry.record_network_facts(db_session, agent, facts)
    agent_registry.record_network_facts(db_session, agent, facts)

    # The second report changed nothing at all, and must still ask. See the
    # module docstring: readiness arrives after the interfaces have stopped
    # moving, and a change gate would never fire again.
    assert fired == [agent.id, agent.id]


def test_the_hello_path_fires_the_trigger(db_session, factories, fired):
    agent = _agent(db_session, factories)
    payload = HelloPayload.model_validate(
        {"networks": [{"name": "eth0", "flags": ["up"], "addrs": [_SAFE_ADDR]}]}
    )

    agent_registry.update_hello_metadata(db_session, agent, payload)

    assert fired == [agent.id]


async def test_the_readiness_path_fires_the_same_trigger(db_session, factories, fired):
    agent = _agent(db_session, factories)
    report = {
        "readiness": [{"collector": "discovery.tcp", "state": "ready"}],
        "networks": [{"name": "eth0", "flags": ["up"], "addrs": [_SAFE_ADDR]}],
    }

    await agent_telemetry.ingest_readiness(db_session, agent, report)

    assert fired == [agent.id]


async def test_a_report_with_no_networks_key_fires_nothing(db_session, factories, fired):
    agent = _agent(db_session, factories)

    await agent_telemetry.ingest_readiness(
        db_session, agent, {"readiness": [{"collector": "discovery.tcp", "state": "ready"}]}
    )
    agent_registry.update_hello_metadata(db_session, agent, HelloPayload.model_validate({}))

    assert fired == []


async def test_schedule_bootstrap_defers_the_work_off_the_reporting_transaction(monkeypatch):
    """D-14's ordering rule: nothing may act before the caller's commit.

    Neither report path awaits between `record_network_facts` and its own
    `db.commit()`, so a task scheduled here cannot start until that commit has
    returned.
    """
    ran: list[int] = []

    async def fake(agent_id: int) -> None:
        ran.append(agent_id)

    monkeypatch.setattr(discovery_bootstrap, "_bootstrap_in_session", fake)

    assert discovery_bootstrap.schedule_bootstrap(77) is True
    assert ran == [], "the bootstrap ran inside the caller's transaction"
    await asyncio.sleep(0.05)
    assert ran == [77]


def test_schedule_bootstrap_reports_rather_than_raises_with_no_loop():
    assert discovery_bootstrap.schedule_bootstrap(77) is False


async def test_a_failing_bootstrap_never_escapes_its_task(monkeypatch):
    async def boom(db, agent_id):  # type: ignore[no-untyped-def]
        raise RuntimeError("bootstrap exploded")

    monkeypatch.setattr(discovery_bootstrap, "run_bootstrap", boom)

    await discovery_bootstrap._bootstrap_in_session(1)


# ── Task 25: the recurring cadence, and the three pause scopes ────────────────
#
# Plan §3 step 5 gives an automatic profile a six-hourly cron, and plan §3's
# closing paragraph says "the central UI can pause automatic discovery globally,
# per agent, or per subnet". Two properties are being pinned here.
#
# **Registration.** `core.scheduler.reload_discovery_jobs` is re-invoked on
# every profile write and *first removes every job it registered*, so a system
# profile has to be re-registered by the same pass that removed it or its cadence
# would survive only until the next unrelated profile edit — and
# `DiscoveryStatusOut.next_scheduled` reads exactly those APScheduler jobs.
#
# **Pausing stops scheduling and deletes nothing.** The three scopes are
# independent by construction — an `app_settings` flag, a `local_discovery`
# grant key, and a `discovery_profiles` column — so each is tested alone and then
# against the other two set to *resumed*, which is the mistake a single
# short-circuiting "is this paused" helper would make.
#
# The global scope is deliberately narrow: it holds **agent-executed** profiles.
# A flag that also stopped the server's own crons would be a second master
# switch beside `app_settings.discovery_enabled` and would make an operator
# pausing an agent fleet silently stop server discovery too.


def _scheduled_profile_ids() -> set[int]:
    """The profile ids APScheduler currently holds a discovery cron for — the
    same jobs `_compute_discovery_status` reads `next_scheduled` off."""
    from app.core.scheduler import get_scheduler

    return {
        int(job.id.removeprefix("discovery_profile_"))
        for job in get_scheduler().get_jobs()
        if job.id.startswith("discovery_profile_")
    }


@pytest.fixture
def app_settings(db_session):  # type: ignore[no-untyped-def]
    """The `app_settings` row.

    The `agent_discovery_paused` **column** is real as of migration
    `0101_discovery_retention_and_global_pause` (Fix A2). Until it landed this
    fixture wrote an *unmapped* attribute and had to hold the instance for the
    whole test to keep the identity map from collecting it — scaffolding that
    could not have failed if the column were dropped, which is precisely how the
    global scope stayed unstorable behind six green tests. It now writes the
    column `discovery_service.global_agent_discovery_paused` reads.
    """
    from app.services.settings_service import get_or_create_settings

    return get_or_create_settings(db_session)


def _pause_globally(app_settings, paused: bool = True) -> None:  # type: ignore[no-untyped-def]
    """Write the mapped column, by name.

    Not a name constant plus `setattr`: that form succeeds against *any*
    attribute name, mapped or not, which is what let these tests pass while the
    storage did not exist — and is why the constant that used to hold the column
    name no longer exists.
    """
    app_settings.agent_discovery_paused = paused


@pytest.fixture
async def running_scheduler():  # type: ignore[no-untyped-def]
    """A started APScheduler bound in place of the process-global one.

    `next_run_time` is computed when a job is added to a *running* scheduler, and
    `DiscoveryStatusOut.next_scheduled` is that value — so a test that asserts on
    it has to start one. Its own instance so the jobs other suites left on the
    global scheduler cannot decide what the earliest next run is.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.core import scheduler as scheduler_module

    previous = scheduler_module.get_scheduler()
    fresh = AsyncIOScheduler()
    scheduler_module.set_scheduler_instance(fresh)
    fresh.start()
    try:
        yield fresh
    finally:
        fresh.shutdown(wait=False)
        scheduler_module.set_scheduler_instance(previous)


async def test_a_system_profiles_cron_survives_the_next_reload_cycle(db_session, factories):
    """`reload_discovery_jobs` removes every discovery job it owns before it
    re-registers, so "was registered once" proves nothing about the cadence an
    hour later. The second reload is the assertion."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _agent(db_session, factories)

    await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    (profile,) = _system_profiles(db_session, agent.id)
    assert profile.id in _scheduled_profile_ids()

    reload_discovery_jobs(db_session)

    assert profile.id in _scheduled_profile_ids()


async def test_the_system_profiles_cadence_is_what_the_discovery_status_reports(
    db_session, factories, running_scheduler
):
    """End to end onto the field the UI renders: the derived six-hourly cron
    (D-7) becomes an APScheduler fire time, and `next_scheduled` is it."""
    from app.api.discovery import _compute_discovery_status

    agent = _agent(db_session, factories)

    await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    (profile,) = _system_profiles(db_session, agent.id)
    assert profile.schedule_cron == discovery_bootstrap.system_profile_cron(agent.id)
    job = running_scheduler.get_job(f"discovery_profile_{profile.id}")
    assert job is not None and job.next_run_time is not None

    status = _compute_discovery_status(db_session)

    assert status.next_scheduled == job.next_run_time.isoformat()


async def test_a_global_pause_stops_scheduling_and_deletes_nothing(
    db_session, factories, app_settings
):
    """M14's widest scope. The profile, its cron expression and its `enabled`
    flag are all still there — only the APScheduler registration is gone, which
    is what "pause" has to mean for a subnet whose history is being kept."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _agent(db_session, factories)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (profile,) = _system_profiles(db_session, agent.id)

    _pause_globally(app_settings)
    reload_discovery_jobs(db_session)

    assert profile.id not in _scheduled_profile_ids()
    assert profile.enabled == 1
    assert profile.schedule_cron == discovery_bootstrap.system_profile_cron(agent.id)
    assert profile.paused_at is None


async def test_a_global_pause_holds_the_agents_profile_and_not_the_servers(
    db_session, factories, app_settings
):
    """The scope of the global flag, written down as a test: it is Slice 4's
    control over agent-executed discovery, not a second `discovery_enabled`.
    Both kinds of profile are present on purpose — a flag tested against an
    agent-free installation would look identical whichever way it was scoped."""
    from app.core.scheduler import reload_discovery_jobs

    server_profile = DiscoveryProfile(
        name="server-side",
        cidr="10.99.0.0/24",
        scan_types=json.dumps(["nmap"]),
        schedule_cron="0 */6 * * *",
        enabled=1,
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
    )
    db_session.add(server_profile)
    db_session.flush()
    agent = _agent(db_session, factories)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (agent_profile,) = _system_profiles(db_session, agent.id)

    _pause_globally(app_settings)
    reload_discovery_jobs(db_session)

    scheduled = _scheduled_profile_ids()
    assert server_profile.id in scheduled
    assert agent_profile.id not in scheduled


async def test_a_per_agent_pause_stops_only_that_agents_profiles(db_session, factories):
    """`local_discovery.auto_discovery_paused` (Task 3). One agent held, the
    fleet beside it untouched."""
    from app.core.scheduler import reload_discovery_jobs

    held = _agent(db_session, factories, config={"auto_discovery_paused": True})
    running = _agent(db_session, factories)
    await discovery_bootstrap.run_bootstrap(db_session, held.id)
    await discovery_bootstrap.run_bootstrap(db_session, running.id)
    (held_profile,) = _system_profiles(db_session, held.id)
    (running_profile,) = _system_profiles(db_session, running.id)

    reload_discovery_jobs(db_session)

    scheduled = _scheduled_profile_ids()
    assert held_profile.id not in scheduled
    assert running_profile.id in scheduled
    assert held_profile.enabled == 1


async def test_a_per_subnet_pause_stops_only_that_subnet(db_session, factories):
    """`discovery_profiles.paused_at` (Task 4). The agent's other segment keeps
    its cadence, which is the whole reason the column is per profile."""
    from app.core.scheduler import reload_discovery_jobs
    from app.core.time import utcnow

    agent = _agent(db_session, factories, facts=_BOTH_FACTS)
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    first, second = _system_profiles(db_session, agent.id)

    first.paused_at = utcnow()
    db_session.flush()
    reload_discovery_jobs(db_session)

    scheduled = _scheduled_profile_ids()
    assert first.id not in scheduled
    assert second.id in scheduled
    assert first.enabled == 1


async def test_a_global_resume_does_not_release_a_paused_agent(db_session, factories, app_settings):
    """The combination clause. Three independent switches means the widest one
    being *off* says nothing about the narrower two."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _agent(db_session, factories, config={"auto_discovery_paused": True})
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (profile,) = _system_profiles(db_session, agent.id)

    _pause_globally(app_settings, paused=False)
    reload_discovery_jobs(db_session)

    assert profile.id not in _scheduled_profile_ids()


async def test_an_unpaused_agent_is_still_held_by_the_global_pause(
    db_session, factories, app_settings
):
    """And the other direction: an agent whose own flag is explicitly `false`
    does not escape a fleet-wide hold."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _agent(db_session, factories, config={"auto_discovery_paused": False})
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (profile,) = _system_profiles(db_session, agent.id)

    _pause_globally(app_settings)
    reload_discovery_jobs(db_session)

    assert profile.id not in _scheduled_profile_ids()


async def test_a_paused_subnet_is_not_released_by_resuming_the_other_two_scopes(
    db_session, factories, app_settings
):
    """The narrowest scope against both wider ones resumed."""
    from app.core.scheduler import reload_discovery_jobs
    from app.core.time import utcnow

    agent = _agent(db_session, factories, config={"auto_discovery_paused": False})
    await discovery_bootstrap.run_bootstrap(db_session, agent.id)
    (profile,) = _system_profiles(db_session, agent.id)
    profile.paused_at = utcnow()
    db_session.flush()

    _pause_globally(app_settings, paused=False)
    reload_discovery_jobs(db_session)

    assert profile.id not in _scheduled_profile_ids()


async def test_a_paused_agent_still_gets_its_profile_but_no_automatic_scan(db_session, factories):
    """Plan §3 step 4's initial scan is scheduling too. A pause that created the
    profile and then scanned it anyway would make the control a lie; a pause that
    refused to create it would lose the subnet's identity and its history, which
    is what `enabled = 0` is reserved for."""
    held = _agent(db_session, factories, config={"auto_discovery_paused": True})

    outcome = await discovery_bootstrap.run_bootstrap(db_session, held.id)

    (profile,) = _system_profiles(db_session, held.id)
    assert outcome.created_profile_ids == (profile.id,)
    assert outcome.queued_job_ids == ()
    assert _jobs(db_session, held.id) == []


async def test_an_unpaused_agent_still_gets_its_initial_scan(db_session, factories):
    """The control for the test above: the suppression must be the pause and not
    a bootstrap that stopped queueing scans at all."""
    agent = _agent(db_session, factories)

    outcome = await discovery_bootstrap.run_bootstrap(db_session, agent.id)

    assert len(outcome.queued_job_ids) == 1
    assert len(_jobs(db_session, agent.id)) == 1
