"""Slice 4 §3: may this agent run this discovery job right now?

Plan §3 lists the preconditions a profile save and a job creation must both
satisfy — active agent, `local_discovery` enabled, compatible collector
readiness, and every target CIDR inside the versioned effective scope — and D-17
adds the tenant rule. Every denial names a machine-readable reason, because the
same answer is rendered on the agent detail page, returned as a 422 detail at
profile/job creation and written to the dispatch audit row; prose would have to
be re-parsed by all three.

The shape deliberately mirrors `tests/services/test_probe_eligibility.py`: the
two eligibility modules answer the same question about the same agent from the
same scope evaluator, and a divergence in either is a bug rather than a
difference of opinion.
"""

from datetime import timedelta

import pytest

from app.core import agent_scope
from app.core.time import utcnow
from app.db.models import Tenant
from app.services import agent_registry
from app.services import discovery_eligibility as elig


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
    """An agent that satisfies every precondition — tests remove one at a time."""
    agent = factories.agent(status=status, **kwargs)
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    return agent


def _tenant(db_session, name: str):
    """No tenant factory exists and this task does not own `tests/factories.py`."""
    tenant = Tenant(name=name)
    db_session.add(tenant)
    db_session.flush()
    return tenant


# ── The happy path ────────────────────────────────────────────────────────────


async def test_healthy_agent_with_an_in_scope_target_is_eligible(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert decision.ok, decision
    assert decision.reason is None


async def test_a_narrower_prefix_inside_the_reported_subnet_is_eligible(
    db_session, factories, presence
):
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.128/25"])

    assert decision.ok, decision


# ── Agent status ──────────────────────────────────────────────────────────────


async def test_unknown_agent_is_ineligible(db_session, factories, presence):
    decision = await elig.evaluate_eligibility(db_session, 999_999, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_MISSING


@pytest.mark.parametrize("status", ["pending", "rejected", "revoked"])
async def test_non_active_agent_is_ineligible(db_session, factories, presence, status):
    agent = _agent(factories, status=status)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_INACTIVE
    assert decision.detail == status


# ── Reachability ──────────────────────────────────────────────────────────────


async def test_offline_agent_is_ineligible(db_session, factories, presence):
    agent = _agent(factories)  # presence() deliberately not called

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_AGENT_OFFLINE


async def test_live_presence_without_a_link_owner_is_ineligible(db_session, factories, monkeypatch):
    """Presence and connection ownership expire together but are written by
    different call sites; only the owner proves a worker can actually deliver."""
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)
    agent = _agent(factories)
    store[f"agent:presence:{agent.id}"] = "{}"

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_NO_LINK_OWNER


async def test_offline_agent_is_eligible_when_the_caller_is_not_dispatching(
    db_session, factories, presence
):
    """D-5: an offline agent parks the job as `waiting_for_agent` and keeps it
    queued, so being offline is a scheduling condition and not a configuration
    error. A profile save that refused it would make the whole feature unusable
    from an agent's first reboot onwards."""
    agent = _agent(factories)

    decision = await elig.evaluate_eligibility(
        db_session, agent.id, targets=["10.0.0.0/24"], require_online=False
    )

    assert decision.ok, decision


# ── The grant ─────────────────────────────────────────────────────────────────


async def test_ungranted_local_discovery_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_CAPABILITY_DISABLED


async def test_disabled_local_discovery_grant_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=False)
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_CAPABILITY_DISABLED


async def test_remote_probe_alone_does_not_grant_discovery(db_session, factories, presence):
    """The two capabilities are separate grants over the same scope evaluator;
    reusing `probe_eligibility.derive_agent_scope` must not drag its capability
    along with it."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_CAPABILITY_DISABLED


# ── Collector readiness (D-8's `discovery.*` rows) ────────────────────────────


async def test_missing_readiness_row_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNKNOWN
    assert decision.detail == "discovery.tcp"


async def test_stale_readiness_is_treated_as_unknown_not_ready(db_session, factories, presence):
    """Readiness rows carry no TTL, so a row that says `ready` may predate an
    outage of any length. Freshness, not state, is what makes it evidence."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(
        agent,
        collector="discovery.tcp",
        state="ready",
        updated_at=utcnow() - timedelta(seconds=elig.READINESS_MAX_AGE_S + 60),
    )
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNKNOWN


async def test_probe_readiness_does_not_stand_in_for_discovery_readiness(
    db_session, factories, presence
):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="probe.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNKNOWN


async def test_degraded_discovery_readiness_is_ineligible(db_session, factories, presence):
    """Unlike a degraded probe collector, a degraded discovery collector is a
    refusal: a probe that half-works reports an error the result path models,
    whereas a sweep that half-works reports *fewer hosts* and is indistinguishable
    from a segment that really is that empty."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(
        agent, collector="discovery.tcp", state="degraded", reason="socket budget exhausted"
    )
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_DEGRADED
    assert decision.detail == "discovery.tcp:degraded"


async def test_unavailable_discovery_readiness_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent)
    factories.agent_capability_readiness(
        agent, collector="discovery.tcp", state="unavailable", reason="no route"
    )
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_READINESS_UNAVAILABLE
    assert decision.detail == "discovery.tcp:unavailable"


async def test_an_unusable_accelerator_collector_does_not_deny(db_session, factories, presence):
    """`discovery.neighbor`, `discovery.icmp` and `discovery.dns` speed a sweep
    up or enrich it; only the connect sweep *is* `agent_connect`. Denying on them
    would make a container without an ICMP socket permanently ineligible for a
    scan it can still perform completely."""
    agent = _agent(factories)
    factories.agent_capability_readiness(agent, collector="discovery.icmp", state="unavailable")
    factories.agent_capability_readiness(agent, collector="discovery.neighbor", state="degraded")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert decision.ok, decision


# ── Tenancy (D-17) ────────────────────────────────────────────────────────────


async def test_mismatched_tenant_is_ineligible(db_session, factories, presence):
    """`probe_eligibility`'s rule verbatim: refuse only when both sides carry a
    tenant and they differ."""
    tenant_a = _tenant(db_session, "discovery-eligibility-a")
    tenant_b = _tenant(db_session, "discovery-eligibility-b")
    agent = _agent(factories, tenant_id=tenant_a.id)
    presence(agent)

    decision = await elig.evaluate_eligibility(
        db_session, agent.id, targets=["10.0.0.0/24"], tenant_id=tenant_b.id
    )

    assert not decision.ok
    assert decision.reason == elig.REASON_TENANT_MISMATCH
    assert decision.detail == f"{tenant_b.id}!={tenant_a.id}"


async def test_tenantless_job_may_run_on_a_tenant_scoped_agent(db_session, factories, presence):
    tenant = _tenant(db_session, "discovery-eligibility-tenantless-job")
    agent = _agent(factories, tenant_id=tenant.id)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert decision.ok, decision


async def test_tenanted_job_may_run_on_a_tenantless_agent(db_session, factories, presence):
    tenant = _tenant(db_session, "discovery-eligibility-tenantless-agent")
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(
        db_session, agent.id, targets=["10.0.0.0/24"], tenant_id=tenant.id
    )

    assert decision.ok, decision


async def test_matching_tenants_are_eligible(db_session, factories, presence):
    tenant = _tenant(db_session, "discovery-eligibility-match")
    agent = _agent(factories, tenant_id=tenant.id)
    presence(agent)

    decision = await elig.evaluate_eligibility(
        db_session, agent.id, targets=["10.0.0.0/24"], tenant_id=tenant.id
    )

    assert decision.ok, decision


# ── Scope (the one evaluator, via `network_in_scope`) ─────────────────────────


async def test_target_outside_the_reported_subnet_is_ineligible(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["192.168.50.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "out_of_scope:192.168.50.0/24"


async def test_a_prefix_only_half_inside_the_reported_subnet_is_ineligible(
    db_session, factories, presence
):
    """`network_in_scope` demands full containment: a /23 straddling the agent's
    /24 describes addresses on a segment it never reported."""
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/23"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "out_of_scope:10.0.0.0/23"


async def test_an_over_wide_prefix_is_ineligible(db_session, factories, presence):
    """The evaluator's own reason travels in `detail`, so a refusal that is
    really about width is not reported as an unremarkable scope miss."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    # `agent_networks` holds exactly one row per agent, so the whole agent is
    # built by hand rather than layering a second report over `_agent`'s.
    factories.agent_network(
        agent, facts=[{"name": "eth0", "flags": ["up"], "addrs": ["10.0.0.5/8"]}]
    )
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/8"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "prefix_too_wide:10.0.0.0/8"


async def test_an_excluded_cidr_is_ineligible(db_session, factories, presence):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent,
        capability="local_discovery",
        enabled=True,
        config={"excluded_cidrs": ["10.0.0.0/25"]},
    )
    factories.agent_network(agent)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "excluded_cidr:10.0.0.0/24"


async def test_agent_with_no_reported_networks_can_discover_nothing(
    db_session, factories, presence
):
    """`agent_scope` denies on an empty scope rather than failing open the way
    `network_acl.is_ip_in_cidrs` would."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "empty_scope:10.0.0.0/24"


async def test_every_target_is_judged_not_only_the_first(db_session, factories, presence):
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(
        db_session, agent.id, targets=["10.0.0.0/25", "192.168.50.0/24"]
    )

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "out_of_scope:192.168.50.0/24"


async def test_an_unparseable_target_is_refused_rather_than_skipped(
    db_session, factories, presence
):
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["not-a-cidr"])

    assert not decision.ok
    assert decision.reason == elig.REASON_OUT_OF_SCOPE
    assert decision.detail == "invalid_destination:not-a-cidr"


async def test_no_targets_asks_only_about_the_agent(db_session, factories, presence):
    """Callers that have no target yet — the revoke and capability-disable paths
    that need to know whether an agent is still allowed to be running discovery
    at all — ask the same question minus the scope clause."""
    agent = _agent(factories)
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id)

    assert decision.ok, decision


async def test_tenantless_agent_and_tenantless_job_are_eligible(db_session, factories, presence):
    """The fourth tenant combination, pinned explicitly rather than by accident.

    `probe_eligibility` refuses only when *both* sides carry a tenant and they
    differ, so all four combinations have to be spelled out here for the mirror to
    be checkable: None/None and None/int and int/None pass, int/int(differing)
    refuses. This is the None/None one — single-tenant installs run entirely in
    it, so a rule that read a missing tenant as "no match" would deny every job
    they ever create.
    """
    agent = _agent(factories)  # no tenant_id
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/24"])

    assert decision.ok, decision


# ── `derive_discovery_scope`'s own grant lookup ────────────────────────────────


def test_scope_lookup_ignores_remote_probe_config_when_discovery_is_ungranted(
    db_session, factories
):
    """An absent `local_discovery` grant derives the *defaults*, never `remote_probe`'s.

    `derive_discovery_scope` resolves the grant itself for callers that hold no
    config (the agent detail page's scope panel, the dispatcher's re-check), and
    it delegates to `probe_eligibility.derive_agent_scope`, whose own
    `config is None` branch looks up the **`remote_probe`** grant. So an
    unresolved `None` passed straight through does not fail — it silently hands
    the agent whatever scope its *probing* grant widened, with no denial anywhere
    to make the substitution visible. The `remote_probe` config below is
    deliberately non-default in both directions so a wrong-grant read shows up as
    both an extra allowed network and a phantom exclusion.
    """
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent,
        capability="remote_probe",
        enabled=True,
        config={"additional_cidrs": ["192.168.77.0/24"], "excluded_cidrs": ["10.0.0.0/25"]},
    )
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24

    scope = elig.derive_discovery_scope(db_session, agent.id)

    assert scope.networks == ("10.0.0.0/24",)
    assert scope.excluded_networks == ()


def test_scope_lookup_reads_the_local_discovery_grants_own_config(db_session, factories):
    """The other half of the same invariant: when both grants exist, the
    `local_discovery` one is the one that configures the discovery scope."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent,
        capability="local_discovery",
        enabled=True,
        config={"excluded_cidrs": ["10.0.0.0/25"]},
    )
    factories.agent_capability_grant(
        agent,
        capability="remote_probe",
        enabled=True,
        config={"additional_cidrs": ["192.168.77.0/24"]},
    )
    factories.agent_network(agent)

    scope = elig.derive_discovery_scope(db_session, agent.id)

    assert scope.networks == ("10.0.0.0/24",)
    assert scope.excluded_networks == ("10.0.0.0/25",)


# ── The limits this module deliberately leaves to its callers ─────────────────


async def test_an_in_scope_target_can_still_exceed_the_grants_address_ceiling(
    db_session, factories, presence
):
    """Eligibility says nothing about how *large* a job is, and the gap is real.

    `MIN_SCOPE_PREFIX_V4 = 16` admits a /16 — 65 536 addresses — while
    `max_addresses_per_job` is capped at 4 096 and defaults to 1 024. So a target
    can be squarely inside the effective scope and still be a job no agent may
    run, which is why the module docstring hands `max_addresses_per_job` and
    `tcp_ports` to the callers that hold the request and why they enforce them
    with `agent_scope.address_count`. If this ever starts denying, the creation-time
    validator's ceiling check has become unreachable and its tests vacuous.
    """
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    # One `agent_networks` row per agent, so the /16 report replaces `_agent`'s /24.
    factories.agent_network(
        agent, facts=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/16"]}]
    )
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    presence(agent)

    decision = await elig.evaluate_eligibility(db_session, agent.id, targets=["10.0.0.0/16"])

    assert decision.ok, decision
    assert agent_scope.address_count(["10.0.0.0/16"]) == 65_536
    granted = agent_registry.structured_grants_dict(db_session, agent.id)["local_discovery"]
    assert granted["config"]["max_addresses_per_job"] < 65_536
