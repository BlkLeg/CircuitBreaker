"""Slice 3 §2: may this agent run this monitor's check right now?

Every denial has to name a machine-readable reason — it is what lands in
`monitor_items.probe_execution_reason`, what the monitor card renders, and what
the run's audit row records — so each test here asserts the reason, not just the
refusal.
"""

from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.db.models import Tenant
from app.services.monitoring import probe_eligibility as elig


class _FakeRedis:
    """The two reads `is_agent_online` / `get_agent_connection_owner` make."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)


@pytest.fixture
def presence(monkeypatch):
    """A Redis double plus a `mark(agent)` helper that brings one agent online.

    Nothing is online until a test says so, so "offline" is the default and a
    test that forgets the call fails loudly rather than passing vacuously.
    """
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    def mark(agent, worker: str = "worker-1") -> None:
        store[f"agent:presence:{agent.id}"] = "{}"
        store[f"agent:connection:{agent.id}"] = worker

    return mark


def _agent(factories, *, status: str = "active", **kwargs):
    agent = factories.agent(status=status, **kwargs)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    return agent


def _tenant(db_session, name: str):
    """No tenant factory exists and this task does not own `tests/factories.py`."""
    tenant = Tenant(name=name)
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _monitor(factories, agent, *, host: str = "10.0.0.9", **kwargs):
    return factories.monitor_item(host=host, check_type="icmp", probe_agent_id=agent.id, **kwargs)


async def test_healthy_agent_in_scope_is_eligible(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert decision.ok, decision
    assert decision.reason is None


async def test_offline_agent_is_ineligible_with_reason_offline(db_session, factories, presence):
    agent = _agent(factories)
    monitor = _monitor(factories, agent)  # presence() deliberately not called

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_OFFLINE


async def test_live_presence_without_a_link_owner_is_ineligible(db_session, factories, monkeypatch):
    """Presence and connection ownership expire together but are written by
    different call sites; only the owner proves a worker can actually deliver."""
    store = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)
    agent = _agent(factories)
    store[f"agent:presence:{agent.id}"] = "{}"
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_NO_LINK_OWNER


async def test_revoked_agent_is_ineligible(db_session, factories, presence):
    agent = _agent(factories, status="revoked")
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_INACTIVE
    assert decision.detail == "revoked"


async def test_missing_remote_probe_grant_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_CAPABILITY_DISABLED


async def test_disabled_remote_probe_grant_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_CAPABILITY_DISABLED


async def test_stale_readiness_is_treated_as_unknown_not_ready(db_session, factories, presence):
    """`agent_capability_readiness` rows have no TTL and `hello.readiness` is
    parsed but never persisted, so a row that says `ready` may predate an outage
    of any length. Freshness, not state, is what makes it evidence."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(
        agent,
        collector="probe.icmp",
        state="ready",
        updated_at=utcnow() - timedelta(seconds=elig.READINESS_MAX_AGE_S + 60),
    )
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNKNOWN


async def test_readiness_for_another_check_type_does_not_count(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="probe.tcp", state="ready")
    presence(agent)
    monitor = _monitor(factories, agent)  # icmp

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNKNOWN


async def test_unavailable_readiness_is_reported_as_unavailable(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(
        agent, collector="probe.icmp", state="unavailable", reason="ping group unusable"
    )
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNAVAILABLE


async def test_target_outside_effective_scope_is_ineligible(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent, host="192.168.50.5")

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "out_of_scope:192.168.50.5"


async def test_hostname_target_is_denied_when_any_resolved_address_is_out_of_scope(
    db_session, factories, presence
):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent, host="app.internal.example.com")

    async def _resolver(host: str) -> list[str]:
        return ["10.0.0.9", "192.168.50.5"]

    decision = await elig.evaluate_eligibility(db_session, monitor, resolver=_resolver)

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "out_of_scope:192.168.50.5"


async def test_unresolvable_hostname_target_is_ineligible(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent, host="nx.internal.example.com")

    async def _resolver(host: str) -> list[str]:
        return []

    decision = await elig.evaluate_eligibility(db_session, monitor, resolver=_resolver)

    assert not decision.ok
    assert decision.reason == elig.REASON_UNRESOLVED_HOST


async def test_mismatched_tenant_is_ineligible(db_session, factories, presence):
    """D-9: refuse only when both sides carry a tenant and they differ."""
    tenant_a = _tenant(db_session, "probe-eligibility-a")
    tenant_b = _tenant(db_session, "probe-eligibility-b")
    agent = _agent(factories, tenant_id=tenant_a.id)
    presence(agent)
    hardware = factories.hardware(tenant_id=tenant_b.id)
    monitor = _monitor(factories, agent, target_type="hardware", target_id=hardware.id)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_TENANT_MISMATCH


async def test_tenantless_monitor_may_run_on_a_tenant_scoped_agent(db_session, factories, presence):
    """D-9's other half: "admin monitors an arbitrary IP from the branch office"
    stays legal — the target is still bounded by the agent's derived scope."""
    tenant = _tenant(db_session, "probe-eligibility-tenantless")
    agent = _agent(factories, tenant_id=tenant.id)
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert decision.ok, decision


async def test_active_run_makes_the_monitor_ineligible_this_tick(db_session, factories, presence):
    """D-6: a monitor that becomes due with a run still in flight skips the
    interval rather than queuing a second run behind an already-slow agent."""
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent)
    factories.monitor_probe_run(monitor, agent, status="dispatched")
    db_session.flush()

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_PREVIOUS_RUN_IN_FLIGHT


async def test_the_run_being_dispatched_is_not_its_own_blocker(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent)
    run = factories.monitor_probe_run(monitor, agent, status="queued")
    db_session.flush()

    decision = await elig.evaluate_eligibility(db_session, monitor, ignore_run_id=run.run_id)

    assert decision.ok, decision


async def test_a_completed_run_does_not_block_the_next_one(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent)
    factories.monitor_probe_run(monitor, agent, status="completed")
    db_session.flush()

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert decision.ok, decision


async def test_agent_with_no_reported_networks_can_probe_nothing(db_session, factories, presence):
    """`agent_scope` denies on an empty scope rather than failing open the way
    `network_acl.is_ip_in_cidrs` would."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    presence(agent)
    monitor = _monitor(factories, agent)

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "empty_scope:10.0.0.9"


async def test_unassigned_monitor_is_ineligible(db_session, factories, presence):
    monitor = factories.monitor_item(host="10.0.0.9", check_type="icmp")

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_MISSING


async def test_the_default_resolver_is_used_and_loopback_stays_blocked(
    db_session, factories, presence
):
    """Exercises the real `getaddrinfo` path (localhost comes from /etc/hosts, so
    no network is involved) and pins that no scope can hand an agent loopback."""
    agent = _agent(factories)
    presence(agent)
    monitor = _monitor(factories, agent, host="localhost")

    decision = await elig.evaluate_eligibility(db_session, monitor)

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail is not None
    assert decision.detail.startswith("special_use:")
