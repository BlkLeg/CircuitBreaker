"""Task 13 / D-8: `capability.readiness` refreshes the agent's directly
connected networks mid-session.

`hello.networks` is sent once, at connect. Without a mid-session refresh a
subnet that appeared on the agent host would not become discoverable until the
next reconnect — which may be days — so `capability.readiness` carries the same
optional `networks` field and `ingest_readiness` forwards it to the *existing*
`agent_registry.record_network_facts`. There is deliberately no second copy of
the facts: `agent_networks.facts` stays the one input to
`core.agent_scope.derive_scope`.

Three rules are pinned here, and each is load-bearing rather than stylistic:

* the forward happens **before** `ingest_readiness`' own `db.commit()`, so the
  refreshed scope and the readiness state it was reported with are one
  transaction — a reader can never see a `generation` bump whose readiness
  report never landed, or the reverse;
* an **absent** key leaves the last report standing (the gate is presence in
  `model_fields_set`, never truthiness), because an agent build predating the
  field omits it entirely and must not erase what a newer build reported;
* an explicit **`[]`** replaces the last report, because an agent that has lost
  every usable interface must be able to say so — otherwise the server keeps
  enforcing a stale, wider-than-reality scope forever, and the generation the
  scheduler cancels in-flight work on never moves. This is why the Go
  `CapabilityReadinessPayload.Networks` carries no `omitempty`.

Payloads are read from `fixtures/agent_frame_corpus.json` rather than
hand-rolled, for the reason `tests/services/test_agent_telemetry.py` gives: the
corpus is the schema of record shared with the Go conformance test, so a
collector-side field rename cannot pass this suite silently.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import AgentCapabilityReadiness, AgentNetwork
from app.schemas.agent_frame import NetworkFacts
from app.services import agent_telemetry

_CORPUS_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "agent_frame_corpus.json"
_WITH_NETWORKS = "capability.readiness — discovery collectors"
_LOST_EVERY_INTERFACE = "capability.readiness — every interface lost"

# The corpus entries above as `record_network_facts` stores them: interfaces
# sorted by name, each with its flags and addresses sorted. Spelled out so a
# change to the normalization fails here rather than silently reshaping the one
# input `derive_scope` reads.
_ETH0_STORED = {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.88.0.4/24"]}
_ETH1_STORED = {
    "name": "eth1",
    "flags": ["broadcast", "up"],
    "addrs": ["10.77.0.9/24", "fd00:a::9/64"],
}


def _corpus_payload(description_prefix: str) -> dict:
    entries = json.loads(_CORPUS_PATH.read_text())
    for entry in entries:
        if entry["description"].startswith(description_prefix):
            return copy.deepcopy(entry["json"]["payload"])
    raise AssertionError(
        f"{_CORPUS_PATH} has no entry described {description_prefix!r} — Task 13 owns that fixture"
    )


def _payload_without_networks() -> dict:
    """The same report as sent by an agent build predating the field: the key is
    missing, not empty."""
    payload = _corpus_payload(_WITH_NETWORKS)
    payload.pop("networks")
    return payload


def _network_row(db, agent_id: int) -> AgentNetwork | None:
    """Keyed on the id rather than the instance: the rollback test below queries
    after its `agents` row is gone, where touching `agent.id` would refresh a
    deleted instance."""
    return (
        db.execute(select(AgentNetwork).where(AgentNetwork.agent_id == agent_id)).scalars().first()
    )


def _readiness_collectors(db, agent_id: int) -> list[str]:
    return list(
        db.execute(
            select(AgentCapabilityReadiness.collector)
            .where(AgentCapabilityReadiness.agent_id == agent_id)
            .order_by(AgentCapabilityReadiness.collector)
        ).scalars()
    )


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    """`get_redis` is a module-level import in `agent_telemetry`, so it is
    patched there rather than on `app.core.redis`. The readiness WS fan-out
    itself is covered by `tests/services/test_agent_telemetry.py`; this file is
    about what reaches the database."""

    async def _get_redis():
        return None

    monkeypatch.setattr(agent_telemetry, "get_redis", _get_redis)


@pytest.mark.asyncio
async def test_readiness_networks_are_staged_before_the_readiness_commit(db_session, factories):
    """The facts must be written *inside* the transaction `ingest_readiness`
    closes, not after it.

    The spy reads `agent_networks` back through the same session at the moment
    `db.commit()` is called, which autoflushes whatever the caller has staged —
    so a forward that ran after the commit (or, worse, committed separately)
    would show an empty table here.
    """
    agent = factories.agent(status="active")
    staged_at_commit: list[list[tuple[int, list]]] = []
    real_commit = db_session.commit

    def _spy_commit() -> None:
        staged_at_commit.append(
            [
                (row.generation, row.facts)
                for row in db_session.execute(
                    select(AgentNetwork).where(AgentNetwork.agent_id == agent.id)
                ).scalars()
            ]
        )
        real_commit()

    db_session.commit = _spy_commit  # type: ignore[method-assign]
    try:
        changed = await agent_telemetry.ingest_readiness(
            db_session, agent, _corpus_payload(_WITH_NETWORKS)
        )
    finally:
        del db_session.commit

    assert changed is True
    assert staged_at_commit == [[(1, [_ETH0_STORED, _ETH1_STORED])]]

    # ... and it is still there afterwards, alongside the readiness rows the
    # same commit made durable.
    row = _network_row(db_session, agent.id)
    assert row is not None
    assert (row.generation, row.facts) == (1, [_ETH0_STORED, _ETH1_STORED])
    assert _readiness_collectors(db_session, agent.id) == [
        "discovery.dns",
        "discovery.icmp",
        "discovery.neighbor",
        "discovery.tcp",
    ]


@pytest.mark.asyncio
async def test_a_failing_commit_discards_both_the_facts_and_the_readiness_rows(
    db_session, factories
):
    """One transaction, proven from the failure side.

    `record_network_facts` documents that the caller owns the commit. If the
    forward committed on its own, releasing this session's savepoint, the facts
    would survive the rollback below while the readiness report they were
    reported with would not.
    """
    agent = factories.agent(status="active")
    agent_id = agent.id

    def _explode() -> None:
        raise RuntimeError("commit failed")

    db_session.commit = _explode  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            await agent_telemetry.ingest_readiness(
                db_session, agent, _corpus_payload(_WITH_NETWORKS)
            )
    finally:
        del db_session.commit

    db_session.rollback()

    assert _network_row(db_session, agent_id) is None
    assert _readiness_collectors(db_session, agent_id) == []


@pytest.mark.asyncio
async def test_readiness_without_a_networks_key_leaves_the_last_report_standing(
    db_session, factories
):
    """Presence in `model_fields_set`, never truthiness: an agent predating the
    field omits the key, and its readiness report must not erase the scope a
    newer build (or the hello) already established."""
    agent = factories.agent(status="active")
    seeded = factories.agent_network(agent, facts=[_ETH0_STORED])
    observed_at = seeded.observed_at
    db_session.expire_all()

    changed = await agent_telemetry.ingest_readiness(db_session, agent, _payload_without_networks())

    assert changed is True  # the readiness rows are new; the facts are not
    row = _network_row(db_session, agent.id)
    assert row is not None
    assert (row.generation, row.facts, row.observed_at) == (1, [_ETH0_STORED], observed_at)


@pytest.mark.asyncio
async def test_an_absent_networks_key_never_reaches_record_network_facts(
    db_session, factories, monkeypatch
):
    """The gate is checked before the call, so a truthiness gate cannot hide
    behind `record_network_facts`' own change detection: an empty list and an
    absent key are indistinguishable once the call is made."""
    agent = factories.agent(status="active")
    calls: list[list[NetworkFacts]] = []
    real = agent_telemetry.record_network_facts

    def _spy(db, agent_, networks):
        calls.append(networks)
        return real(db, agent_, networks)

    monkeypatch.setattr(agent_telemetry, "record_network_facts", _spy)

    await agent_telemetry.ingest_readiness(db_session, agent, _payload_without_networks())
    assert calls == []

    await agent_telemetry.ingest_readiness(db_session, agent, _corpus_payload(_WITH_NETWORKS))

    # Forwarded as parsed models, not raw mappings — `record_network_facts`
    # normalizes by attribute access.
    assert len(calls) == 1
    assert [(n.name, n.flags, n.addrs) for n in calls[0]] == [
        ("eth0", ["up", "broadcast"], ["10.88.0.4/24"]),
        ("eth1", ["up", "broadcast"], ["10.77.0.9/24", "fd00:a::9/64"]),
    ]


@pytest.mark.asyncio
async def test_an_explicit_empty_networks_list_replaces_the_last_report(db_session, factories):
    """D-8's load-bearing half. An agent that lost every interface says `[]`,
    and the generation must move so the scheduler cancels in-flight work and
    stops enforcing a scope wider than reality."""
    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=[_ETH0_STORED, _ETH1_STORED])
    db_session.expire_all()

    await agent_telemetry.ingest_readiness(
        db_session, agent, _corpus_payload(_LOST_EVERY_INTERFACE)
    )

    row = _network_row(db_session, agent.id)
    assert row is not None
    assert (row.generation, row.facts) == (2, [])


# ── The cancellation the refreshed scope produces (D-16) ──────────────────────
# A readiness report that moves the scope retires the dispatches the new scope
# no longer authorizes. `agent_discovery`'s cancellation section states the rule
# every trigger obeys: the rows are closed inside the caller's transaction, and
# **nothing is published until that transaction commits**. `ingest_readiness` is
# the trigger's synchronous half, so the two tests below pin both directions —
# an agent must never be told to abandon a dispatch a rollback then reinstates,
# and it must be told once the rollback can no longer happen.

# The agent's own subnet, and the interface that puts it there. The corpus
# report at `_WITH_NETWORKS` moves the agent to 10.88/10.77, so a job aimed at
# this subnet loses both its target and the scope version it was dispatched
# under.
_OWN_SUBNET = "10.20.30.0/24"
_OWN_INTERFACE = {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]}


def _agent_with_a_live_dispatch(db_session, factories):
    """An agent holding one dispatched discovery job, in the state
    `agent_discovery._claim` leaves it in.

    Mirrors `tests/test_discovery.py`'s `_dispatched_job` rather than importing
    it — that helper belongs to the API suite, and a cross-suite import would
    make this file fail for edits made over there.
    """
    import secrets
    from datetime import timedelta

    from app.core.time import utcnow, utcnow_iso
    from app.db.models import ScanJob
    from app.services.discovery_eligibility import derive_discovery_scope

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent, facts=[_OWN_INTERFACE])
    db_session.expire_all()
    job = ScanJob(
        scan_agent_id=agent.id,
        target_cidr=_OWN_SUBNET,
        scan_types_json='["agent_connect"]',
        source_type="agent",
        status="running",
        dispatch_id=secrets.token_hex(16),
        dispatch_status="dispatched",
        dispatch_deadline_at=utcnow() + timedelta(minutes=5),
        scope_version=derive_discovery_scope(db_session, agent.id).version,
        tenant_id=agent.tenant_id,
        created_at=utcnow_iso(),
    )
    db_session.add(job)
    db_session.flush()
    return agent, job


@pytest.fixture
def cancel_frames(monkeypatch):
    """Every control frame a cancellation would put on the wire. Patched on
    `agent_registry`, which is the attribute `publish_discovery_cancels`
    resolves through."""
    from app.services import agent_registry

    frames: list[tuple[int, dict]] = []

    async def _spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", _spy)
    return frames


def _cancels(frames):
    from app.schemas.agent_frame import TYPE_DISCOVERY_CANCEL

    return [frame["payload"] for _, frame in frames if frame["type"] == TYPE_DISCOVERY_CANCEL]


async def _drain_the_loop() -> None:
    """Give anything a trigger scheduled with `create_task` its chance to run,
    so "nothing was published" cannot pass merely because nothing has been
    scheduled *yet*. Two ticks: one to start the task, one for anything it
    yields on."""
    import asyncio

    for _ in range(2):
        await asyncio.sleep(0)


async def test_a_readiness_commit_that_fails_publishes_no_discovery_cancel(
    db_session, factories, cancel_frames
):
    """Nothing is published from inside the transaction (D-16).

    A cancel published before the commit that closes its job is a cancel the
    rollback un-does: the agent abandons the sweep, the server still shows the
    job running, and it sits there until Task 23's pass expires it under the
    wrong reason. The failure injected here is the one that actually happens —
    a serialization failure or a concurrent writer's constraint violation
    surfacing at `ingest_readiness`' own `db.commit()`, after the scope has
    already been staged.
    """
    agent, _job = _agent_with_a_live_dispatch(db_session, factories)

    def _explode() -> None:
        raise RuntimeError("commit failed")

    db_session.commit = _explode  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            await agent_telemetry.ingest_readiness(
                db_session, agent, _corpus_payload(_WITH_NETWORKS)
            )
    finally:
        del db_session.commit

    await _drain_the_loop()

    assert _cancels(cancel_frames) == []


async def test_a_committed_readiness_scope_change_publishes_its_discovery_cancel(
    db_session, factories, cancel_frames
):
    """The other half: the trigger still fires for this caller.

    `record_network_facts` owns the trigger for both of its callers precisely so
    neither can silently lack it, and moving the publish out to the caller must
    not turn `capability.readiness` into the frame that closes jobs without ever
    telling the agent.
    """
    from app.services import agent_discovery

    agent, job = _agent_with_a_live_dispatch(db_session, factories)

    await agent_telemetry.ingest_readiness(db_session, agent, _corpus_payload(_WITH_NETWORKS))

    assert _cancels(cancel_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_SCOPE_CHANGED}
    ]
    db_session.refresh(job)
    assert job.status == agent_discovery.CANCELLED_JOB_STATUS
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
