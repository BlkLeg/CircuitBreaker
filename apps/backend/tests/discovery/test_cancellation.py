"""Tests for cancellation on every path: an in-flight agent job's control
frame, disabling a profile, a network report that drops or moves a job's
target, and a scope change while a job is still waiting for its agent.

Split out of the former tests/test_discovery.py.
"""

import pytest

from tests.discovery.helpers import (
    _AGENT_HOST,
    _AGENT_INTERFACES,
    _AGENT_SUBNET,
    JOBS_URL,
    PROFILES_URL,
    _cancels,
    _dispatched_job,
    _eligible_agent,
)

# ---------------------------------------------------------------------------
# Cancellation on every path (Slice 4, D-14 / D-16)
# ---------------------------------------------------------------------------
#
# Five events retire an in-flight discovery dispatch: the job is cancelled, its
# profile is disabled, the agent's scope moves under it, the `local_discovery`
# grant is turned off, or the agent is revoked. The last two are pinned in
# `tests/api/test_agents_api.py` because that is where their triggers live; the
# first three are here.
#
# Two properties carry the weight and are asserted separately every time:
#
# * the job is closed in the database *first*, so a finding arriving afterwards
#   is refused whether or not any `discovery.cancel` was ever delivered — the
#   server never relies on the agent honouring a cancel;
# * delivery is best-effort and never raises, so an agent that vanished cannot
#   turn a profile edit into a 500.


async def _assert_a_late_finding_is_refused(db_session, agent, job):
    """The security property: rejection follows from the closed row, not from
    the agent having received (or honoured) a `discovery.cancel`."""
    import secrets

    from app.core.time import utcnow
    from app.db.models import ScanResult
    from app.services import agent_discovery

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session,
            agent,
            {
                "dispatch_id": job.dispatch_id,
                "scan_job_id": job.id,
                "finding_id": secrets.token_hex(16),
                "kind": "host",
                "observed_at": utcnow().isoformat(),
                "ip_address": _AGENT_HOST,
            },
        )
    assert agent_discovery.REASON_DISPATCH_CLOSED in str(excinfo.value)
    assert db_session.query(ScanResult).filter(ScanResult.scan_job_id == job.id).count() == 0


# ── DELETE /discovery/jobs/{id} ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelling_an_agent_job_publishes_discovery_cancel(
    client, auth_headers, db_session, factories, cancel_frames
):
    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)

    resp = await client.delete(f"{JOBS_URL}/{job.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    assert _cancels(cancel_frames) == [{"dispatch_id": job.dispatch_id, "reason": None}]
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.dispatch_status == "cancelled"
    await _assert_a_late_finding_is_refused(db_session, agent, job)


@pytest.mark.asyncio
async def test_cancelling_a_server_job_publishes_no_discovery_cancel(
    client, auth_headers, db_session, cancel_frames
):
    """`scan_agent_id is None` is the server scanner; there is no lease to retire
    and no agent to tell."""
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob

    job = ScanJob(
        scan_types_json='["nmap"]', status="running", source_type="manual", created_at=utcnow_iso()
    )
    db_session.add(job)
    db_session.flush()

    resp = await client.delete(f"{JOBS_URL}/{job.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_cancelling_an_agent_job_survives_an_agent_that_vanished(
    client, auth_headers, db_session, factories, monkeypatch
):
    """Delivery is best-effort. A publisher that blows up must not turn an
    operator's cancel into a 500, and must not leave the lease open."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    monkeypatch.setattr(
        agent_registry,
        "publish_agent_control_frame",
        AsyncMock(side_effect=RuntimeError("redis is gone")),
    )

    resp = await client.delete(f"{JOBS_URL}/{job.id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    db_session.refresh(job)
    assert job.dispatch_status == "cancelled"
    # And the refusal still holds. This is the only configuration in which the
    # agent provably never heard the cancel, so it is the one that actually
    # proves the server is not relying on it having heard one.
    await _assert_a_late_finding_is_refused(db_session, agent, job)


def _let_another_writer_finish_the_job(db_session, monkeypatch, **winning_values):
    """Make some other writer take the job terminal inside the window
    `DELETE /discovery/jobs/{id}` has between deciding the job is cancellable and
    writing it.

    That window is real and uncoordinated: the endpoint reads the row, checks its
    status, and only then writes, while `discovery_dispatch.finalize_agent_job`
    accepts the agent's terminal summary on the `/link` connection and
    `_scan_finalize` ends a server scan on its own thread. The interleaving is
    made deterministic by wrapping the endpoint's own write; the winning row is
    written through Core with `synchronize_session=False`, exactly as the real
    winners' compare-and-sets are, so the endpoint keeps holding the stale ORM
    object it would hold in production — a row that moved under the write is the
    whole subject here.
    """
    from sqlalchemy import update

    from app.api import discovery as discovery_api
    from app.db.models import ScanJob

    write = discovery_api._close_cancelled_job

    def _finished_first(db, job):
        db.execute(
            update(ScanJob)
            .where(ScanJob.id == job.id)
            .values(**winning_values)
            .execution_options(synchronize_session=False)
        )
        return write(db, job)

    monkeypatch.setattr(discovery_api, "_close_cancelled_job", _finished_first)


@pytest.mark.asyncio
async def test_cancelling_an_agent_job_that_completed_first_keeps_the_outcome_that_won(
    client, auth_headers, db_session, factories, cancel_frames, monkeypatch
):
    """A completed scan must never be shown to the operator as cancelled.

    `finalize_agent_job` had already written the `scan_completed` audit row and
    told every client the job completed; a blind `job.status = "cancelled"` here
    left the row saying `cancelled` with `dispatch_status=completed` and
    `progress_phase=done` — a self-contradiction no reader can resolve, and a
    `discovery.cancel` for a dispatch that closed itself. The write is a
    compare-and-set, so the loser reports the outcome that actually stands.
    """
    from app.core.time import utcnow_iso

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    _let_another_writer_finish_the_job(
        db_session,
        monkeypatch,
        status="completed",
        dispatch_status="completed",
        progress_phase="done",
        completed_at=utcnow_iso(),
    )

    resp = await client.delete(f"{JOBS_URL}/{job.id}", headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Job is already completed"
    db_session.refresh(job)
    assert (job.status, job.dispatch_status, job.progress_phase) == (
        "completed",
        "completed",
        "done",
    )
    # And nothing was published: the dispatch closed itself, so there is no lease
    # left for the agent to be told to abandon.
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_cancelling_a_server_job_that_completed_first_keeps_the_outcome_that_won(
    client, auth_headers, db_session, cancel_frames, monkeypatch
):
    """The server arm carries the identical race and now the identical guard.

    `_scan_finalize` closes the job on the scan's own thread with no reference to
    this endpoint, so the same read-then-write window applies. Making the write
    conditional does not change how a server scan is cancelled — that stays
    cooperative — it only stops the endpoint overwriting a scan that finished
    first.
    """
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob

    job = ScanJob(
        scan_types_json='["nmap"]', status="running", source_type="manual", created_at=utcnow_iso()
    )
    db_session.add(job)
    db_session.flush()
    _let_another_writer_finish_the_job(
        db_session, monkeypatch, status="completed", completed_at=utcnow_iso()
    )

    resp = await client.delete(f"{JOBS_URL}/{job.id}", headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Job is already completed"
    db_session.refresh(job)
    assert job.status == "completed"
    # Untouched, because a server job never held a dispatch: the endpoint must
    # not hand it an agent job's vocabulary on its way past.
    assert job.dispatch_status is None


# ── Disabling a profile ───────────────────────────────────────────────────────


def _agent_profile(db_session, agent, *, name="agent-owned"):
    from app.core.time import utcnow_iso
    from app.db.models import DiscoveryProfile

    now = utcnow_iso()
    profile = DiscoveryProfile(
        name=name,
        cidr=_AGENT_SUBNET,
        normalized_cidr=_AGENT_SUBNET,
        scan_agent_id=agent.id,
        scan_types='["agent_connect"]',
        enabled=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(profile)
    db_session.flush()
    return profile


@pytest.mark.asyncio
async def test_disabling_a_profile_cancels_its_in_flight_jobs(
    client, auth_headers, db_session, factories, cancel_frames
):
    """D-14 names profile-disable explicitly because it is the trigger an
    implementation forgets — and it is exactly the moment D-7's
    subnet-disappearance path fires."""
    from app.services import agent_discovery

    agent = _eligible_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)

    resp = await client.patch(
        f"{PROFILES_URL}/{profile.id}", json={"enabled": False}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.dispatch_status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_PROFILE_DISABLED
    await _assert_a_late_finding_is_refused(db_session, agent, job)


@pytest.mark.asyncio
async def test_disabling_a_profile_leaves_another_profiles_job_alone(
    client, auth_headers, db_session, factories, cancel_frames
):
    agent = _eligible_agent(factories)
    disabled = _agent_profile(db_session, agent, name="going-away")
    other = _agent_profile(db_session, agent, name="still-running")
    doomed = _dispatched_job(db_session, agent, profile_id=disabled.id)
    survivor = _dispatched_job(db_session, agent, profile_id=other.id)

    resp = await client.patch(
        f"{PROFILES_URL}/{disabled.id}", json={"enabled": False}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(doomed)
    db_session.refresh(survivor)
    assert doomed.status == "cancelled"
    assert survivor.status == "running"
    assert survivor.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_a_profile_edit_that_does_not_disable_cancels_nothing(
    client, auth_headers, db_session, factories, cancel_frames
):
    agent = _eligible_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)

    resp = await client.patch(
        f"{PROFILES_URL}/{profile.id}", json={"name": "renamed"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "running"
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_the_subnet_disappearance_entry_point_cancels_the_same_way(
    db_session, factories, cancel_frames
):
    """Task 24 disables a system profile whose subnet went away and owes the same
    cancellation. It calls one entry point rather than re-deriving the edit, so
    the two paths cannot answer differently — and because it runs on the event
    loop, this is also where the published frame is observable."""
    import asyncio

    from app.services import agent_discovery, discovery_profiles_service

    agent = _eligible_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)

    discovery_profiles_service.disable_profile(db_session, profile.id, actor="discovery-bootstrap")
    await asyncio.sleep(0)

    db_session.refresh(profile)
    assert profile.enabled == 0
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_PROFILE_DISABLED
    assert _cancels(cancel_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_PROFILE_DISABLED}
    ]


@pytest.mark.asyncio
async def test_disabling_a_profile_survives_an_agent_that_vanished(
    client, auth_headers, db_session, factories, monkeypatch
):
    """D-14's "never raising on delivery failure", at the endpoint an operator
    actually uses."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = _eligible_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)
    monkeypatch.setattr(
        agent_registry,
        "publish_agent_control_frame",
        AsyncMock(side_effect=RuntimeError("redis is gone")),
    )

    resp = await client.patch(
        f"{PROFILES_URL}/{profile.id}", json={"enabled": False}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    db_session.refresh(job)
    assert job.status == "cancelled"
    await _assert_a_late_finding_is_refused(db_session, agent, job)


def test_disabling_a_profile_off_the_event_loop_still_closes_its_jobs(db_session, factories):
    """The synchronous half of "delivery never raises".

    `schedule_discovery_cancels` borrows `monitor_service._publish_soon`, which
    publishes nothing at all when no loop is running — the case for every `def`
    route FastAPI hands to its threadpool and for Task 24's bootstrap when it
    runs outside a request. That path must still be a clean disable: the job is
    closed in the database, the reason is D-4's, and nothing is raised at the
    caller. `_assert_a_late_finding_is_refused` is not reachable from a `def`
    test, and does not need to be — the closed row it reads is asserted here.
    """
    from app.services import agent_discovery, discovery_profiles_service

    agent = _eligible_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)

    discovery_profiles_service.disable_profile(db_session, profile.id, actor="discovery-bootstrap")

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.dispatch_status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_PROFILE_DISABLED


# ── A scope change under a live dispatch (D-16) ───────────────────────────────


def _scope_version(db_session, agent):
    """`agent_networks.generation` — the scope version a network report moves.

    The signal a caller has that the report changed anything, and deliberately
    not `record_network_facts`' return value: that is the *cancellation* the
    report produced, and it is empty both when nothing changed and when a real
    change touched no job worth cancelling (D-16). `generation` is the version
    the scheduler, the UI and the audit trail all cite, so it is the one the
    tests below cite too.
    """
    from app.db.models import AgentNetwork

    row = db_session.query(AgentNetwork).filter(AgentNetwork.agent_id == agent.id).first()
    return row.generation if row else None


async def _report_networks(db_session, agent, interfaces):
    """What `agent_telemetry.ingest_readiness` and `hello` both funnel into.

    Commits, then publishes — in that order, and both here rather than one here
    and one at the call sites, because that is precisely what `ingest_readiness`
    does now that E1 moved delivery out of `record_network_facts`: the rows close
    inside the caller's transaction, and the agent is told to abandon its
    dispatch only once that transaction is durable. A helper that stopped at the
    commit would leave every `cancel_frames` assertion below asserting about a
    publish no caller in production omits.

    Returns the scope version the report left behind, so a caller can assert on
    what a scope change actually signals.
    """
    from app.schemas.agent_frame import NetworkFacts
    from app.services import agent_discovery, agent_registry

    cancellation = agent_registry.record_network_facts(
        db_session, agent, [NetworkFacts(**iface) for iface in interfaces]
    )
    db_session.commit()
    await agent_discovery.publish_discovery_cancels(cancellation)
    return _scope_version(db_session, agent)


@pytest.mark.asyncio
async def test_a_network_report_that_drops_a_live_jobs_target_cancels_it(
    db_session, factories, cancel_frames
):
    from app.services import agent_discovery

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    before = _scope_version(db_session, agent)

    assert (
        await _report_networks(
            db_session,
            agent,
            [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.99.0.5/24"]}],
        )
        != before
    )

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
    assert _cancels(cancel_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_SCOPE_CHANGED}
    ]
    await _assert_a_late_finding_is_refused(db_session, agent, job)


@pytest.mark.asyncio
async def test_a_network_report_that_only_moves_the_scope_version_cancels_it(
    db_session, factories, cancel_frames
):
    """D-16: the job carries the version that was in force when its request was
    built. A second interface leaves the original target in scope and still moves
    the version, and the ingest path refuses every finding under a version nobody
    authorized — so the dispatch has to be retired rather than left to starve."""
    from app.services import agent_discovery
    from app.services.discovery_eligibility import derive_discovery_scope

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    before = _scope_version(db_session, agent)

    assert (
        await _report_networks(
            db_session,
            agent,
            [
                {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]},
                {"name": "eth1", "flags": ["broadcast", "up"], "addrs": ["10.21.0.5/24"]},
            ],
        )
        != before
    )

    scope = derive_discovery_scope(db_session, agent.id)
    assert scope.version != job.scope_version
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED


@pytest.mark.asyncio
async def test_an_unchanged_network_report_cancels_nothing(db_session, factories, cancel_frames):
    """A scope version that does not move is the steady state — every
    heartbeat-adjacent readiness frame re-reports the same interfaces, and a
    counter that ticked on each of them would say "this agent's scope changed"
    about nothing."""
    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    before = _scope_version(db_session, agent)

    assert await _report_networks(db_session, agent, _AGENT_INTERFACES) == before

    db_session.refresh(job)
    assert job.status == "running"
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_a_job_still_waiting_for_its_agent_survives_a_scope_change_it_fits(
    db_session, factories, cancel_frames
):
    """A parked job (D-5) holds no lease and no version snapshot, so a scope that
    moved without dropping its target must leave it alone — cancelling it would
    fail a scan that is still perfectly authorized."""
    agent = _eligible_agent(factories)
    job = _dispatched_job(
        db_session,
        agent,
        status="queued",
        dispatch_id=None,
        dispatch_status="queued",
        scope_version=None,
        progress_phase="waiting_for_agent",
    )
    before = _scope_version(db_session, agent)

    # The scope really did move — asserted on the version, because the
    # cancellation `record_network_facts` returns is empty here and *must* be:
    # an empty one is this test's expected outcome, not evidence the report was
    # a no-op.
    assert (
        await _report_networks(
            db_session,
            agent,
            [
                {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]},
                {"name": "eth1", "flags": ["broadcast", "up"], "addrs": ["10.21.0.5/24"]},
            ],
        )
        != before
    )

    db_session.refresh(job)
    assert job.status == "queued"
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_a_job_still_waiting_for_its_agent_is_cancelled_when_its_target_goes(
    db_session, factories, cancel_frames
):
    """The other half of the rule above. A parked job has no version snapshot to
    compare, so containment is the only thing that can retire it — and it has to,
    because the subnet it was going to sweep is no longer one the agent is on.
    Nothing is published: there is no lease the agent could be holding."""
    from app.services import agent_discovery

    agent = _eligible_agent(factories)
    job = _dispatched_job(
        db_session,
        agent,
        status="queued",
        dispatch_id=None,
        dispatch_status="queued",
        scope_version=None,
        progress_phase="waiting_for_agent",
    )
    before = _scope_version(db_session, agent)

    assert (
        await _report_networks(
            db_session,
            agent,
            [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.99.0.5/24"]}],
        )
        != before
    )

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_a_network_report_whose_cancel_cannot_be_delivered_still_refuses_findings(
    db_session, factories, monkeypatch
):
    """The scope trigger's half of the same property: `record_network_facts` runs
    inside the `/link` read loop, and the delivery its caller awaits afterwards
    is best-effort — `publish_discovery_cancels` swallows a dead Redis, so
    nothing downstream would notice a cancel that never reached the agent. The
    rows are closed and committed before the publish is attempted at all, which
    is what makes that safe."""
    from unittest.mock import AsyncMock

    from app.services import agent_discovery, agent_registry

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    before = _scope_version(db_session, agent)
    monkeypatch.setattr(
        agent_registry,
        "publish_agent_control_frame",
        AsyncMock(side_effect=RuntimeError("redis is gone")),
    )

    assert (
        await _report_networks(
            db_session,
            agent,
            [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.99.0.5/24"]}],
        )
        != before
    )

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
    await _assert_a_late_finding_is_refused(db_session, agent, job)


def test_a_cancellation_reason_outside_the_d4_vocabulary_is_refused(db_session, factories):
    """D-4's `error_reason` set is closed and `scan_jobs.error_reason` is read by
    the history filter and the audit trail. A reason this module invented is a
    programming error, caught here rather than persisted."""
    from app.services import agent_discovery

    agent = _eligible_agent(factories)
    _dispatched_job(db_session, agent)

    with pytest.raises(ValueError, match="not a scan job error reason"):
        agent_discovery.cancel_agent_dispatches(db_session, agent.id, reason="operator_said_so")


@pytest.mark.asyncio
async def test_publishing_a_cancellation_never_raises(db_session, factories, monkeypatch):
    """Directly, because every trigger reaches delivery differently — one awaits
    it, one fires it onto the loop — and only this asserts the guarantee itself
    rather than one caller's insulation from it."""
    from unittest.mock import AsyncMock

    from app.services import agent_discovery, agent_registry

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    cancellation = agent_discovery.cancel_agent_dispatches(
        db_session, agent.id, reason=agent_discovery.ERROR_CAPABILITY_DISABLED
    )
    db_session.commit()
    monkeypatch.setattr(
        agent_registry,
        "publish_agent_control_frame",
        AsyncMock(side_effect=RuntimeError("redis is gone")),
    )

    assert await agent_discovery.publish_discovery_cancels(cancellation) == 0
    db_session.refresh(job)
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_a_cancelled_dispatch_tells_the_clients_its_job_went_terminal(
    db_session, factories, monkeypatch
):
    """These jobs are closed by a bulk write rather than by `finalize_agent_job`,
    so without this they would go terminal with no client ever hearing about it
    and the history page would show a scan that never ends."""
    from app.services import agent_discovery, discovery_service

    events: list[tuple[str, dict]] = []

    async def _spy(event_type, payload):
        events.append((event_type, payload))

    monkeypatch.setattr(discovery_service, "_emit_ws_event", _spy)

    agent = _eligible_agent(factories)
    job = _dispatched_job(db_session, agent)
    cancellation = agent_discovery.cancel_agent_dispatches(
        db_session, agent.id, reason=agent_discovery.ERROR_CAPABILITY_DISABLED
    )
    db_session.commit()
    await agent_discovery.publish_discovery_cancels(cancellation)

    assert (
        "job_update",
        {
            "job": {
                "id": job.id,
                "status": "cancelled",
                "error_reason": agent_discovery.ERROR_CAPABILITY_DISABLED,
                "progress_percent": 100,
            }
        },
    ) in events
