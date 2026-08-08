"""Slice 4 §4/§7: what the backend will and will not accept as a `discovery.finding`.

The mirror of `test_agent_probe_ingest.py`, and for the same reason: this is the
one path on which a remote agent writes rows into the discovery review queue, so
every rule here is a security invariant rather than a preference. The size cap
runs before anything parses, the (dispatch, job, agent) triple is matched before
anything is written, an address outside the job's own targets or outside the
scope snapshotted on the job is refused, a duplicate is inert, and no untrusted
string the agent chose ever reaches a log line or an `agent_events` detail —
including on the pydantic path, where `ValidationError.__str__` would happily
quote the offending banner.

Three of these need more than a single sequential call to mean anything, and are
written accordingly: the per-dispatch ceiling is raced on two real connections
because the sequential version of the same assertion passes against a naive
read-modify-write, the closed-dispatch guard moves `status` and `dispatch_status`
independently because the two columns really do move independently, and the
constants are pinned to their magnitudes rather than to each other.
"""

import asyncio
import inspect
import ipaddress
import logging
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow, utcnow_iso
from app.db.models import Agent, AgentEvent, ScanJob, ScanResult, Tenant
from app.services import (
    agent_discovery,
    discovery_eligibility,
    discovery_merge,
    discovery_service,
)
from app.services.agent_capabilities import _LOCAL_DISCOVERY_BOUNDS

_FACTS = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.60.0.5/24"]}]


def _tenant(db_session, name: str):  # type: ignore[no-untyped-def]
    """No tenant factory exists and this task does not own `tests/factories.py`."""
    tenant = Tenant(name=f"{name}-{secrets.token_hex(4)}")
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _agent(db_session, factories, *, config=None, facts=None, tenant=None, status="active"):  # type: ignore[no-untyped-def]
    tenant = tenant if tenant is not None else _tenant(db_session, "discovery-ingest")
    agent = factories.agent(status=status, tenant_id=tenant.id)
    factories.agent_capability_grant(
        agent, capability="local_discovery", enabled=True, config=config or {}
    )
    factories.agent_network(agent, facts=_FACTS if facts is None else facts)
    db_session.flush()
    return agent


def _job(db_session, agent, **kwargs):  # type: ignore[no-untyped-def]
    """A job in the state the dispatcher (Task 20) leaves it in."""
    defaults = {
        "scan_agent_id": agent.id,
        "dispatch_id": secrets.token_hex(16),
        "dispatch_status": "dispatched",
        "dispatch_deadline_at": utcnow() + timedelta(seconds=300),
        "scope_version": agent_discovery.derive_discovery_scope(db_session, agent.id).version,
        "target_cidr": "10.60.0.0/24",
        "status": "running",
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


def _payload(job, **kwargs):  # type: ignore[no-untyped-def]
    payload = {
        "dispatch_id": job.dispatch_id,
        "scan_job_id": job.id,
        "finding_id": secrets.token_hex(16),
        "kind": "host",
        "observed_at": utcnow().isoformat(),
        "ip_address": "10.60.0.9",
        "mac_address": "aa:bb:cc:dd:ee:01",
        "hostname": "printer.lan",
        "open_ports": [{"port": 80, "protocol": "tcp", "banner": "HTTP/1.0 200 OK"}],
        "evidence": ["neighbor:reachable", "tcp:80"],
    }
    payload.update(kwargs)
    return payload


def _results(db_session, job):  # type: ignore[no-untyped-def]
    return db_session.query(ScanResult).filter(ScanResult.scan_job_id == job.id).all()


def _events(db_session, agent):  # type: ignore[no-untyped-def]
    return db_session.query(AgentEvent).filter(AgentEvent.agent_id == agent.id).all()


@pytest.fixture
def emitted(monkeypatch):  # type: ignore[no-untyped-def]
    """`_emit_ws_event` is the only cross-worker event path; spy on it so a test
    can assert that a rejected or duplicated finding fans out to nobody."""
    calls: list[tuple[str, dict]] = []

    async def spy(event_type: str, payload: dict) -> None:
        calls.append((event_type, payload))

    monkeypatch.setattr(discovery_service, "_emit_ws_event", AsyncMock(side_effect=spy))
    return calls


# ── Size, before anything parses ──────────────────────────────────────────────


async def test_oversized_finding_is_rejected_before_the_payload_is_parsed(
    db_session, factories, emitted
):
    """16 KiB, enforced *first*. Nothing upstream bounds an inbound frame:
    `ws_agents.link_stream` reads the socket with a bare `receive_bytes()` and
    `receive_frame` only parses JSON, so this handler is the cap. The payload
    below is also unauthenticated garbage (a dispatch_id belonging to nobody) —
    the size refusal still has to be the one that fires, which is what proves
    the ordering."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    payload = _payload(
        job,
        dispatch_id="f" * 32,
        evidence=["x" * 1024] * 16,
        hostname="y" * 253,
        open_ports=[{"port": p, "protocol": "tcp", "banner": "z" * 512} for p in range(1, 41)],
    )

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, agent, payload)

    assert str(agent_discovery.MAX_FINDING_BYTES) in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_from_an_inactive_agent_is_rejected(db_session, factories, emitted):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    agent.status = "revoked"
    db_session.flush()

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding):
        await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert _results(db_session, job) == []
    assert emitted == []


async def test_malformed_finding_is_a_protocol_violation(db_session, factories):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, finding_id="NOT-HEX")
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_PROTOCOL_VIOLATION


# ── Authentication, as a triple ───────────────────────────────────────────────


async def test_finding_for_an_unknown_dispatch_is_a_capability_violation(
    db_session, factories, emitted
):
    """A dispatch_id that matches no job is an authorization failure, not a
    schema one — it is the shape a stolen or guessed token takes."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, dispatch_id=secrets.token_hex(16))
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_for_another_agents_dispatch_is_a_capability_violation(
    db_session, factories, emitted
):
    tenant = _tenant(db_session, "shared")
    owner = _agent(db_session, factories, tenant=tenant)
    intruder = _agent(db_session, factories, tenant=tenant)
    job = _job(db_session, owner)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, intruder, _payload(job))

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_whose_scan_job_id_disagrees_with_the_dispatch_is_rejected(
    db_session, factories, emitted
):
    """The triple must agree in full. `scan_job_id` is guessable and
    `dispatch_id` is not, so a payload naming both must not be allowed to
    write against whichever one the server happens to look up first."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    other = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, scan_job_id=other.id)
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert _results(db_session, job) == [] and _results(db_session, other) == []
    assert emitted == []


async def test_finding_whose_job_tenant_disagrees_with_the_agent_is_rejected(
    db_session, factories, emitted
):
    """Plan §8: tenant context is derived from the job/agent. A job whose tenant
    has drifted from the reporting agent's is not a job this agent may write
    into, whatever the dispatch token says."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, tenant_id=_tenant(db_session, "other").id)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert _results(db_session, job) == []
    assert emitted == []


# ── Targets and the scope snapshotted on the job ──────────────────────────────


async def test_finding_outside_the_jobs_targets_is_rejected_and_audited(
    db_session, factories, emitted
):
    """The dispatch named 10.60.0.0/24. An agent that answers about 10.60.1.7
    is reporting on a segment nobody authorized, even though its own scope may
    well cover it."""
    agent = _agent(
        db_session,
        factories,
        facts=[
            {
                "name": "eth0",
                "flags": ["broadcast", "up"],
                "addrs": ["10.60.0.5/24", "10.60.1.5/24"],
            }
        ],
    )
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, ip_address="10.60.1.7")
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert agent_discovery.REASON_OUT_OF_TARGET in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_is_judged_against_the_scope_snapshotted_on_the_job(
    db_session, factories, emitted
):
    """D-16. The agent's live scope is not the authority here: a sender that
    could move its own scope between dispatch and ingest — by reporting a new
    interface — would otherwise widen what it is allowed to report about. The
    job carries the version that was in force when the request was built, and a
    finding arriving under any other version is refused."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, scope_version="stale-version-from-an-earlier-dispatch")

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert agent_discovery.ERROR_SCOPE_CHANGED in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_for_an_excluded_address_is_rejected(db_session, factories, emitted):
    """In the job's target and under the job's own scope version, but inside an
    administrator's exclusion — so `agent_scope` refuses it and ingest does too.
    The exclusion is the one rule an agent cannot be trusted to have applied."""
    agent = _agent(db_session, factories, config={"excluded_cidrs": ["10.60.0.128/25"]})
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, ip_address="10.60.0.200")
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    assert "excluded_cidr" in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


# ── A closed dispatch is closed ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "closed",
    [
        {"dispatch_status": "cancelled", "status": "cancelled"},
        {"dispatch_status": "completed", "status": "completed"},
        {"dispatch_status": "expired", "status": "failed"},
        # The two columns move independently, so they are pinned independently:
        # `DELETE /discovery/jobs/{id}` cancels the job without touching the
        # dispatch lease, and the reconciler expires the lease without having
        # moved the job yet. A guard that read only one of them would admit a
        # finding for work an operator has already called off — which is why
        # `_assert_dispatch_open` checks both, and why a parametrization that
        # only ever moved them together could not tell the two apart.
        {"dispatch_status": "dispatched", "status": "cancelled"},
        {"dispatch_status": "cancelled", "status": "running"},
    ],
)
async def test_finding_after_the_dispatch_closed_is_rejected(
    db_session, factories, emitted, closed
):
    """Cancellation is best-effort and the backend stays authoritative: a
    finding for a dispatch the server has already closed — by cancelling it or
    by accepting its terminal summary — is refused on arrival regardless of
    whether the cancel was ever delivered."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, **closed)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert agent_discovery.REASON_DISPATCH_CLOSED in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


async def test_finding_past_the_dispatch_deadline_and_grace_is_rejected(
    db_session, factories, emitted
):
    """`discovery.finding` is a data frame and therefore spools across an
    outage, keeping its original producer `TS`. The lease is judged against the
    server's own clock, because a spooled batch replayed an hour later must not
    walk past the deadline the reconciler has already given up on."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, dispatch_deadline_at=utcnow() - timedelta(seconds=3600))

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert agent_discovery.REASON_LATE_FINDING in str(excinfo.value)
    assert _results(db_session, job) == []
    assert emitted == []


async def test_a_finding_inside_the_late_grace_is_still_accepted(db_session, factories, emitted):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, dispatch_deadline_at=utcnow() - timedelta(seconds=5))

    disposition = await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert disposition == agent_discovery.DISPOSITION_ACCEPTED
    assert agent_discovery.LATE_FINDING_GRACE == timedelta(seconds=30)


# ── The happy path, idempotency and counters ──────────────────────────────────


async def test_accepted_finding_writes_one_result_and_emits_one_event(
    db_session, factories, emitted
):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    disposition = await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert disposition == agent_discovery.DISPOSITION_ACCEPTED
    (result,) = _results(db_session, job)
    assert result.ip_address == "10.60.0.9"
    assert result.discovery_agent_id == agent.id
    assert result.source_type == "agent"
    assert [e for e, _ in emitted] == ["result_added"]
    assert emitted[0][1]["job_id"] == job.id
    assert emitted[0][1]["result"]["id"] == result.id


async def test_duplicate_finding_inserts_one_result_and_emits_no_second_event(
    db_session, factories, emitted
):
    """The idempotency key is `uq_scan_results_job_finding`, not a pre-check:
    two spool replays racing on separate connections both pass a `SELECT` and
    only the index can stop the second `INSERT`."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    payload = _payload(job)

    assert await agent_discovery.ingest_discovery_finding(db_session, agent, payload) == (
        agent_discovery.DISPOSITION_ACCEPTED
    )
    second = await agent_discovery.ingest_discovery_finding(db_session, agent, payload)

    assert second == agent_discovery.DISPOSITION_DUPLICATE
    assert len(_results(db_session, job)) == 1
    assert [e for e, _ in emitted] == ["result_added"]

    db_session.expire_all()
    stored = db_session.get(ScanJob, job.id)
    assert (stored.finding_count, stored.hosts_found) == (1, 1)


async def test_counters_increment_per_accepted_finding(db_session, factories, emitted):
    """D-10: the agent path increments, because it has no batch to write
    absolutely from. `hosts_found` plus exactly one of new/updated/conflict per
    accepted finding, and `finding_count` for every one of them."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    factories.hardware(
        name="known-host",
        mac_address="AA:BB:CC:DD:EE:02",
        ip_address="10.60.0.11",
        tenant_id=agent.tenant_id,
    )
    factories.hardware(
        name="renamed-host",
        mac_address="AA:BB:CC:DD:EE:03",
        ip_address="10.60.0.12",
        tenant_id=agent.tenant_id,
    )
    db_session.flush()

    await agent_discovery.ingest_discovery_finding(
        db_session, agent, _payload(job, ip_address="10.60.0.10", mac_address="aa:bb:cc:dd:ee:01")
    )
    await agent_discovery.ingest_discovery_finding(
        db_session,
        agent,
        _payload(job, ip_address="10.60.0.11", mac_address="aa:bb:cc:dd:ee:02", hostname=None),
    )
    await agent_discovery.ingest_discovery_finding(
        db_session,
        agent,
        _payload(job, ip_address="10.60.0.12", mac_address="aa:bb:cc:dd:ee:03", hostname="moved"),
    )

    db_session.expire_all()
    stored = db_session.get(ScanJob, job.id)
    assert stored.finding_count == 3
    assert stored.hosts_found == 3
    assert (stored.hosts_new, stored.hosts_updated, stored.hosts_conflict) == (1, 1, 1)
    assert stored.last_finding_at is not None


async def test_mac_and_ip_are_normalized_before_matching(db_session, factories, emitted):
    """The neighbour cache reports `net.HardwareAddr.String()`, which is
    lowercase, and every Hardware row the nmap scanner ever wrote is uppercase.
    Normalizing the *input* is what makes the match happen without relaxing the
    server path's SQL."""
    agent = _agent(
        db_session,
        factories,
        facts=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["fd60::5/64"]}],
    )
    job = _job(db_session, agent, target_cidr="fd60::/64")
    hw = factories.hardware(
        name="v6-host",
        mac_address="AA:BB:CC:DD:EE:0F",
        ip_address="fd60::1",
        tenant_id=agent.tenant_id,
    )
    db_session.flush()

    await agent_discovery.ingest_discovery_finding(
        db_session,
        agent,
        _payload(
            job,
            ip_address="FD60:0000:0000:0000:0000:0000:0000:0001",
            mac_address="aa:bb:cc:dd:ee:0f",
            hostname="v6-host",
        ),
    )

    (result,) = _results(db_session, job)
    assert result.ip_address == "fd60::1"
    assert result.mac_address == "AA:BB:CC:DD:EE:0F"
    assert (result.matched_entity_type, result.matched_entity_id) == ("hardware", hw.id)
    assert result.state == "matched"


async def test_banner_is_carried_through_as_untrusted_text(db_session, factories, emitted):
    """`ScanResult.banner` is an unbounded `Text` column, so the pydantic cap is
    the only bound there is — and the bytes themselves are kept verbatim,
    because a review queue that sanitizes the evidence is not evidence."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    banner = "SSH-2.0-OpenSSH_9.6 <script>alert(1)</script>"

    await agent_discovery.ingest_discovery_finding(
        db_session,
        agent,
        _payload(job, open_ports=[{"port": 22, "protocol": "tcp", "banner": banner}]),
    )

    (result,) = _results(db_session, job)
    assert result.banner == banner
    assert result.open_ports_json == [
        {"port": 22, "protocol": "tcp", "service": "SSH", "state": "open"}
    ]


async def test_result_tenant_comes_from_the_job_and_never_from_the_payload(
    db_session, factories, emitted
):
    """D-17. Asserting only that a payload-supplied tenant was ignored would
    pass against a NULL and prove nothing, so the non-NULL assertion is the
    point of the test."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    intruder_tenant = _tenant(db_session, "payload-claimed")

    await agent_discovery.ingest_discovery_finding(
        db_session, agent, _payload(job, tenant_id=intruder_tenant.id)
    )

    (result,) = _results(db_session, job)
    assert result.tenant_id is not None
    assert result.tenant_id == agent.tenant_id == job.tenant_id
    assert result.tenant_id != intruder_tenant.id


# ── The per-dispatch finding ceiling ──────────────────────────────────────────


def test_the_finding_budget_constants_are_pinned_to_their_magnitudes() -> None:
    """Their *values*, not their relationships to each other.

    Every other assertion about these constants is written in terms of the
    constants themselves, so a typo that moved one would move both sides of the
    comparison and nothing would fail. Task 16 calls the summary allowance
    "small" — it is headroom for a frame that arrives once per dispatch plus a
    retry or two, not a second budget — and the dispatch ceiling is the
    `max_addresses_per_job` grant ceiling plus exactly that allowance, read from
    `agent_capabilities` here so a change to the grant bound has to come past
    this test.
    """
    assert agent_discovery.SUMMARY_FINDING_ALLOWANCE == 4
    assert agent_discovery.SUMMARY_FINDING_ALLOWANCE <= 8, "an allowance, not a second budget"
    assert _LOCAL_DISCOVERY_BOUNDS["max_addresses_per_job"][1] == 4096
    assert agent_discovery.MAX_FINDINGS_PER_DISPATCH == 4096 + 4
    # Plan §4's per-finding size limit. Only an oversized fixture bounds this
    # from above elsewhere, which would leave a 16 MiB "limit" passing.
    assert agent_discovery.MAX_FINDING_BYTES == 16 << 10 == 16384


def test_finding_ceiling_is_derived_from_the_grants_address_budget() -> None:
    """A 2048-address /21 target would otherwise admit unbounded distinct
    agent-chosen `finding_id`s, each fanning out through `_emit_ws_event` to
    every connected client."""
    assert agent_discovery.max_findings_per_dispatch({"max_addresses_per_job": 256}) == (
        256 + agent_discovery.SUMMARY_FINDING_ALLOWANCE
    )
    # A missing, malformed or over-large grant value falls back to the server's
    # own hard ceiling rather than to "no limit".
    assert agent_discovery.max_findings_per_dispatch({}) == (
        agent_discovery.MAX_FINDINGS_PER_DISPATCH
    )
    assert agent_discovery.max_findings_per_dispatch({"max_addresses_per_job": 10**9}) == (
        agent_discovery.MAX_FINDINGS_PER_DISPATCH
    )
    assert agent_discovery.max_findings_per_dispatch({"max_addresses_per_job": True}) == (
        agent_discovery.MAX_FINDINGS_PER_DISPATCH
    )


async def test_finding_beyond_the_ceiling_is_refused_and_closes_the_job(
    db_session, factories, emitted
):
    agent = _agent(db_session, factories, config={"max_addresses_per_job": 1})
    job = _job(db_session, agent)
    ceiling = agent_discovery.max_findings_per_dispatch({"max_addresses_per_job": 1})

    for i in range(ceiling):
        await agent_discovery.ingest_discovery_finding(
            db_session,
            agent,
            _payload(job, ip_address=str(ipaddress.ip_address("10.60.0.20") + i)),
        )
    accepted = len(_results(db_session, job))
    assert accepted == ceiling
    assert len(emitted) == ceiling

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, ip_address="10.60.0.99")
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_CAPABILITY_VIOLATION
    # No row, no event: the N+1th finding buys the agent nothing at all.
    assert len(_results(db_session, job)) == accepted
    assert len(emitted) == ceiling

    db_session.expire_all()
    stored = db_session.get(ScanJob, job.id)
    assert stored.status == "failed"
    assert stored.error_reason == agent_discovery.ERROR_AGENT_EXECUTION_ERROR
    assert stored.finding_count == ceiling

    violations = [e for e in _events(db_session, agent) if e.event_type == "capability_violation"]
    assert len(violations) == 1
    assert agent_discovery.REASON_FINDING_CEILING in violations[0].detail["reason"]


# ── Summary findings ──────────────────────────────────────────────────────────


async def test_summary_finding_is_validated_here_and_finalized_by_task_21(
    db_session, factories, emitted
):
    """A summary carries no address, so it takes the same triple/lease checks
    and none of the address checks. It writes no `ScanResult` and emits no
    `result_added`; terminal finalization is Task 21's."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    disposition = await agent_discovery.ingest_discovery_finding(
        db_session,
        agent,
        _payload(
            job,
            kind="summary",
            terminal=True,
            ip_address=None,
            mac_address=None,
            hostname=None,
            open_ports=[],
            outcome="completed",
            hosts_found=3,
            addresses_scanned=254,
        ),
    )

    assert disposition == agent_discovery.DISPOSITION_SUMMARY
    assert _results(db_session, job) == []
    assert emitted == []


async def test_summary_for_a_closed_dispatch_is_still_refused(db_session, factories, emitted):
    agent = _agent(db_session, factories)
    job = _job(db_session, agent, dispatch_status="cancelled", status="cancelled")

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding):
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, kind="summary", terminal=True, outcome="cancelled")
        )


async def test_host_finding_without_an_address_is_rejected(db_session, factories, emitted):
    """`scan_results.ip_address` is NOT NULL, so an addressless host finding
    would otherwise be an IntegrityError inside the `/link` read loop."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, ip_address=None)
        )

    assert excinfo.value.event_type == agent_discovery.EVENT_PROTOCOL_VIOLATION
    assert _results(db_session, job) == []


# ── Log hygiene (plan §7) ─────────────────────────────────────────────────────


async def test_a_crlf_hostname_never_forges_a_second_log_record(
    db_session, factories, emitted, caplog
):
    """Log injection. `hostname` is a PTR answer from a resolver the agent does
    not control, so a name carrying `\\r\\n` plus a forged level prefix is the
    exact payload this rule exists for — and the answer is not to escape it but
    to keep it out of the log line entirely."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    hostname = "printer\r\n2026-01-01 CRITICAL app.services: agent 999 approved"

    with caplog.at_level(logging.DEBUG):
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, hostname=hostname)
        )

    assert caplog.records, "the accepted path must leave an audit line to inspect"
    for record in caplog.records:
        assert "\n" not in record.getMessage()
        assert "\r" not in record.getMessage()
        assert "printer" not in record.getMessage()

    # The untrusted name still reaches the review queue verbatim — it is the
    # evidence an operator is being asked to judge.
    (result,) = _results(db_session, job)
    assert result.hostname == hostname


async def test_rejection_reasons_carry_an_address_and_a_code_and_nothing_else(
    db_session, factories, emitted, caplog
):
    """Plan §7: `banner`, `hostname` and `evidence` never appear in a reason
    string, a log line or an `agent_events` detail. An operator reading the
    audit trail must not be reading attacker-authored text."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo,
    ):
        await agent_discovery.ingest_discovery_finding(
            db_session,
            agent,
            _payload(
                job,
                ip_address="10.60.9.9",
                hostname="secret-hostname",
                evidence=["secret-evidence"],
                open_ports=[{"port": 80, "protocol": "tcp", "banner": "secret-banner"}],
            ),
        )

    reason = str(excinfo.value)
    assert "10.60.9.9" in reason
    for leak in ("secret-hostname", "secret-evidence", "secret-banner"):
        assert leak not in reason
        assert all(leak not in r.getMessage() for r in caplog.records)


async def test_a_rejection_reason_is_bounded_and_single_line(db_session, factories):
    """Every reason goes through `core.log_sanitize.safe_log_fragment`, so even
    the one untrusted value a reason is allowed to carry — the address — cannot
    grow a newline or run to 40 KiB."""
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session, agent, _payload(job, ip_address="10.60.0.9\r\nINJECTED")
        )

    reason = str(excinfo.value)
    assert "\n" not in reason and "\r" not in reason
    assert len(reason) < 200


async def test_a_schema_rejection_never_echoes_the_offending_untrusted_value(
    db_session, factories, emitted, caplog
):
    """The pydantic path is the one that *wants* to leak.

    `ValidationError.__str__` embeds `input_value=`, so a reason built from
    `str(exc)` — the obvious refactor — would quote the very hostname or banner
    plan §7 exists to keep out of a log line and an `agent_events.detail`. Both
    offending values carry the marker at the *front*, because the echo pydantic
    prints is truncated.

    The last assertion is the point: it proves the marker really was reachable,
    so this test cannot pass by having failed validation somewhere else.
    """
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)
    leak = "LEAKED-OBSERVATION"

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo,
    ):
        await agent_discovery.ingest_discovery_finding(
            db_session,
            agent,
            _payload(
                job,
                # Over the 253-char bound `ScanResult.hostname`'s schema imposes,
                # and well under the 16 KiB size cap, so the schema is what
                # refuses it.
                hostname=leak + "x" * 300,
                open_ports=[{"port": 80, "protocol": "tcp", "banner": leak + "z" * 600}],
            ),
        )

    assert str(excinfo.value) == "payload schema is invalid"
    assert excinfo.value.event_type == agent_discovery.EVENT_PROTOCOL_VIOLATION
    assert leak not in str(excinfo.value)
    assert all(leak not in record.getMessage() for record in caplog.records)
    assert _results(db_session, job) == []
    assert emitted == []
    # The `ValidationError` survives as `__cause__` for whoever is debugging a
    # dispatch locally, and is deliberately never rendered into the reason the
    # `agent_link` handler audits.
    assert leak in str(excinfo.value.__cause__)


# ── What ingest deliberately does not do (D-5, plan §5) ───────────────────────


def test_ingest_reaches_neither_the_reconciler_nor_auto_merge() -> None:
    """D-5 and plan §5, as a test rather than a reviewer's grep.

    `services/discovery_reconciler.py` heals discovery *readiness* — the nmap
    capability — and touches no `ScanJob` row, so the finding path has no
    business in it; the dispatch lease's reconciliation is Task 23's separate
    loop. `discovery_merge._auto_merge_result` writes `Hardware`, and an
    untrusted remote executor's finding must reach an operator first. Only
    import statements are scanned so that a comment naming either module stays
    legal, and indented ones are included so a lazy import inside a function
    cannot slip past.
    """
    imports = [
        line.strip()
        for line in inspect.getsource(agent_discovery).splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not [line for line in imports if "discovery_reconciler" in line]
    assert not [line for line in imports if "auto_merge" in line]


async def test_an_accepted_finding_is_left_pending_and_never_auto_merged(
    db_session, factories, emitted, monkeypatch
):
    """The import guard above cannot see a call routed through another module,
    so the two bindings that exist are spied instead: `discovery_merge`'s own
    and the by-name copy `discovery_service` imported at module load. An agent
    finding lands in the review queue as `pending`; merging it is the operator's
    decision or the profile's, never the reporting agent's."""
    merged: list[object] = []
    for module in (discovery_merge, discovery_service):
        monkeypatch.setattr(
            module, "_auto_merge_result", lambda *args, **kwargs: merged.append(args)
        )
    agent = _agent(db_session, factories)
    job = _job(db_session, agent)

    disposition = await agent_discovery.ingest_discovery_finding(db_session, agent, _payload(job))

    assert disposition == agent_discovery.DISPOSITION_ACCEPTED
    assert merged == []
    (result,) = _results(db_session, job)
    assert (result.state, result.merge_status) == ("new", "pending")


def test_one_named_wrapper_bridges_the_database_to_a_discovery_scope() -> None:
    """There must be exactly one `derive_discovery_scope`.

    `discovery_eligibility` owns it — it is the module every §3 checkpoint
    already calls — and ingest reads the *same* function so a fix to the config
    fallback (an agent with no `local_discovery` grant row must not silently
    inherit its `remote_probe` scope) cannot land in one copy only. Two
    same-named wrappers over `probe_eligibility.derive_agent_scope` is how the
    dispatcher and the ingest path come to disagree about what an agent may
    report on.
    """
    assert agent_discovery.derive_discovery_scope is discovery_eligibility.derive_discovery_scope


# ── The ceiling predicate must be decidable, and it must be a CAS ─────────────


def test_finding_count_is_never_null_so_the_ceiling_predicate_is_decidable(
    db_session, factories
) -> None:
    """`ScanJob.finding_count` has a `server_default` and no Python-side
    default, and the ceiling is enforced as `finding_count < ceiling` — a NULL
    there would evaluate UNKNOWN, match no row, and make the very first finding
    of a dispatch close the job as an execution error.

    Three things together make that unreachable rather than merely unlikely, and
    all three are asserted because no one of them is enough:

    * the dispatcher never sets the column, and the server default fills it (0);
    * an ORM caller that sets it to `None` *explicitly* still gets 0 — for a
      column carrying a default SQLAlchemy reads `None` as "no value given" and
      omits it from the INSERT rather than writing NULL;
    * and `nullable=False` catches the one path that could still name NULL — a
      Core insert that bypasses the ORM's omission — as an `IntegrityError`
      rather than as a row the ceiling can never match.

    So no fix is needed in `db/models.py`; this test is the documentation that
    the CAS predicate is decidable on every row that can exist.
    """
    column = ScanJob.__table__.c.finding_count
    assert column.nullable is False
    assert column.server_default is not None

    agent = _agent(db_session, factories)
    job = _job(db_session, agent)  # `_job` never sets finding_count, like the dispatcher
    explicit_none = _job(db_session, agent, finding_count=None)
    db_session.expire_all()
    assert db_session.get(ScanJob, job.id).finding_count == 0
    assert db_session.get(ScanJob, explicit_none.id).finding_count == 0

    savepoint = db_session.begin_nested()
    with pytest.raises(IntegrityError):
        db_session.execute(
            insert(ScanJob).values(
                status="running",
                scan_types_json='["agent_connect"]',
                source_type="agent",
                created_at=utcnow_iso(),
                finding_count=None,
            )
        )
    savepoint.rollback()


def test_two_concurrent_ingests_at_the_ceiling_admit_exactly_one(setup_db, emitted) -> None:
    """The ceiling is a compare-and-set, and only two real connections prove it.

    Driven sequentially the same assertion passes against a naive
    read-modify-write: both readers see `ceiling - 1`, both write `ceiling`, and
    the agent gets one extra finding per connection it opens — which is exactly
    the shape of a spool replayed on a second link after a reconnect.

    The rows are committed on their own connection because `db_session`'s
    SAVEPOINT isolation is invisible to any other connection (the pattern
    `tests/api/test_ws_agents_enroll.py` documents), and are deleted again in
    `finally` for the same reason: nothing rolls a real commit back, and rows
    that survive leak into every later test in the session.
    """
    from app.db.session import SessionLocal
    from tests.factories import Factories

    grant_config = {"max_addresses_per_job": 1}
    ceiling = agent_discovery.max_findings_per_dispatch(grant_config)

    with SessionLocal() as setup:
        tenant = Tenant(name=f"discovery-cas-{secrets.token_hex(4)}")
        setup.add(tenant)
        setup.flush()
        factories = Factories(setup)
        agent = factories.agent(status="active", tenant_id=tenant.id)
        factories.agent_capability_grant(
            agent, capability="local_discovery", enabled=True, config=grant_config
        )
        factories.agent_network(agent, facts=_FACTS)
        setup.flush()
        job = ScanJob(
            scan_agent_id=agent.id,
            dispatch_id=secrets.token_hex(16),
            dispatch_status="dispatched",
            dispatch_deadline_at=utcnow() + timedelta(seconds=300),
            scope_version=agent_discovery.derive_discovery_scope(setup, agent.id).version,
            target_cidr="10.60.0.0/24",
            status="running",
            scan_types_json='["agent_connect"]',
            source_type="agent",
            tenant_id=tenant.id,
            created_at=utcnow_iso(),
            # One short of the ceiling: exactly one of the two racers may win.
            finding_count=ceiling - 1,
        )
        setup.add(job)
        setup.commit()
        agent_id, job_id, tenant_id = agent.id, job.id, tenant.id
        dispatched = SimpleNamespace(id=job.id, dispatch_id=job.dispatch_id)

    barrier = threading.Barrier(2)

    def _ingest(address: str) -> str:
        with SessionLocal() as session:
            payload = _payload(dispatched, ip_address=address)
            agent_row = session.get(Agent, agent_id)
            barrier.wait(timeout=10)
            try:
                asyncio.run(agent_discovery.ingest_discovery_finding(session, agent_row, payload))
            except agent_discovery.InvalidDiscoveryFinding as exc:
                return str(exc)
            return agent_discovery.DISPOSITION_ACCEPTED

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(_ingest, ["10.60.0.31", "10.60.0.32"]))

        accepted = [o for o in outcomes if o == agent_discovery.DISPOSITION_ACCEPTED]
        refused = [o for o in outcomes if o != agent_discovery.DISPOSITION_ACCEPTED]
        assert len(accepted) == 1, outcomes
        assert agent_discovery.REASON_FINDING_CEILING in refused[0]

        with SessionLocal() as check:
            stored = check.get(ScanJob, job_id)
            assert stored.finding_count == ceiling
            assert stored.status == "failed"
            rows = check.query(ScanResult).filter(ScanResult.scan_job_id == job_id).all()
            assert len(rows) == 1
        assert len(emitted) == 1
    finally:
        with SessionLocal() as cleanup:
            # `agent_events`, the grant and the network facts cascade with the
            # agent; the job and its results are deleted first so the order does
            # not depend on which FK carries ON DELETE CASCADE today.
            cleanup.execute(delete(ScanResult).where(ScanResult.scan_job_id == job_id))
            cleanup.execute(delete(ScanJob).where(ScanJob.id == job_id))
            cleanup.execute(delete(Agent).where(Agent.id == agent_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
