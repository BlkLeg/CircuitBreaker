"""Tests for the admission gate an agent-targeted profile or scan must clear:
creation-time validation on the profile API, the same gate re-applied at job
creation, and the same checks again as an operator actually reaches the agent
through the API.

Split out of the former tests/test_discovery.py.
"""

import pytest

from app.services import discovery_admission, discovery_dispatch
from tests.discovery.helpers import (
    _AGENT_INTERFACES,
    _AGENT_SUBNET,
    _OVERSIZED_INTERFACES,
    _OVERSIZED_SUBNET,
    PROFILES_URL,
    SCAN_URL,
    _agent_profile_payload,
    _eligible_agent,
    _make_profile,
)

# ---------------------------------------------------------------------------
# Creation-time validation of an agent-targeted profile or scan (Slice 4, §3/§7)
# ---------------------------------------------------------------------------
#
# Plan §3 requires the same preconditions at profile save and at job creation, and
# §7 names four checkpoints in all. These are the first two. Every refusal is a 422
# whose `reason` comes from `discovery_eligibility`'s closed vocabulary (or, for the
# two limits that module deliberately leaves to its callers, from the Go collector's
# own `internal/collect/discover` codes), so one set of strings is rendered wherever
# the answer is given. It is validation *in addition to* the dispatch-time re-check,
# never instead of it: a scope can change between a save and the job it produces.


@pytest.mark.asyncio
async def test_profile_for_an_eligible_agent_is_created(client, auth_headers, factories):
    """The happy path, so every 422 below is known to come from what it removed."""
    agent = _eligible_agent(factories)
    resp = await client.post(PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected", "revoked"])
async def test_profile_for_a_non_active_agent_is_422(client, auth_headers, factories, status):
    """§7: pending, rejected and revoked agents can never scan."""
    agent = _eligible_agent(factories, status=status)
    resp = await client.post(PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "agent_inactive"
    assert resp.json()["detail"]["detail"] == status


@pytest.mark.asyncio
async def test_profile_for_an_ungranted_agent_is_422(client, auth_headers, factories):
    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=_AGENT_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    resp = await client.post(PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "capability_disabled"


@pytest.mark.asyncio
async def test_profile_for_a_degraded_collector_is_422(client, auth_headers, factories):
    agent = _eligible_agent(factories, readiness="degraded")
    resp = await client.post(PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "readiness_degraded"


@pytest.mark.asyncio
async def test_profile_with_an_out_of_scope_target_is_422(client, auth_headers, factories):
    agent = _eligible_agent(factories)
    resp = await client.post(
        PROFILES_URL,
        json=_agent_profile_payload(agent, cidr="192.168.50.0/24"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()["detail"]
    assert body["reason"] == "out_of_scope"
    # The evaluator's own reason, so a width refusal is not reported as a miss.
    assert body["detail"] == "out_of_scope:192.168.50.0/24"


@pytest.mark.asyncio
async def test_profile_larger_than_the_address_ceiling_is_422(client, auth_headers, factories):
    """`MIN_SCOPE_PREFIX_V4 = 16` admits a /16 — 65 536 addresses — while
    `max_addresses_per_job` defaults to 1 024 and is capped at 4 096, so an
    in-scope target can still be a job no agent may run."""
    agent = _eligible_agent(
        factories,
        interfaces=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}],
    )
    resp = await client.post(
        PROFILES_URL,
        json=_agent_profile_payload(agent, cidr="10.20.0.0/16"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()["detail"]
    assert body["reason"] == "address_limit_exceeded"
    assert body["detail"] == "65536>1024"


@pytest.mark.asyncio
async def test_profile_naming_an_ungranted_port_is_422(client, auth_headers, factories):
    agent = _eligible_agent(factories)
    resp = await client.post(
        PROFILES_URL,
        json=_agent_profile_payload(agent, nmap_arguments="-p 9999"),
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()["detail"]
    assert body["reason"] == "port_not_granted"
    assert body["detail"] == "9999"


@pytest.mark.asyncio
async def test_patch_repointing_a_profile_at_an_ineligible_agent_is_422(
    client, auth_headers, db_session, factories
):
    """Plan §3 says "profile save", which is both verbs: an edit that moves the
    execution location is judged exactly as the create was."""
    from app.db.models import DiscoveryProfile

    agent = factories.agent(status="active")  # no grant, no networks, no readiness
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')

    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"scan_types": ["agent_connect"], "scan_agent_id": agent.id},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "capability_disabled"
    assert db_session.get(DiscoveryProfile, profile_id).scan_agent_id is None


@pytest.mark.asyncio
async def test_patch_disabling_a_profile_whose_agent_was_revoked_still_works(
    client, auth_headers, db_session, factories
):
    """D-14 makes disabling a profile a cancellation trigger, so the one edit that
    stops a profile has to stay reachable exactly when its agent has become
    ineligible. An unconditional re-check would strand every profile naming a
    revoked agent in the enabled state."""
    from app.db.models import DiscoveryProfile

    agent = _eligible_agent(factories)
    created = await client.post(
        PROFILES_URL, json=_agent_profile_payload(agent), headers=auth_headers
    )
    assert created.status_code == 200, created.text
    agent.status = "revoked"
    db_session.flush()

    resp = await client.patch(
        f"{PROFILES_URL}/{created.json()['id']}",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert db_session.get(DiscoveryProfile, created.json()["id"]).enabled == 0


# ---------------------------------------------------------------------------
# The same gate on job creation
# ---------------------------------------------------------------------------
#
# Driven straight through `create_scan_job` so that a refusal is read off the
# exception rather than off a status code. Task 20 landed the router, so both
# HTTP entry points now carry the execution location too, and the section below
# ("Reaching the agent through the API") pins the same gate where an operator
# actually meets it.


def _create_agent_scan(db_session, agent, **overrides):
    from app.services import discovery_service

    kwargs = {
        "target_cidr": _AGENT_SUBNET,
        "scan_types": ["agent_connect"],
        "scan_agent_id": agent.id,
    }
    kwargs.update(overrides)
    return discovery_service.create_scan_job(db_session, **kwargs)


def test_scan_job_for_an_eligible_agent_is_created(db_session, factories):
    agent = _eligible_agent(factories)
    job = _create_agent_scan(db_session, agent)
    assert job.id is not None
    assert job.target_cidr == _AGENT_SUBNET


@pytest.mark.parametrize("status", ["pending", "rejected", "revoked"])
def test_scan_job_for_a_non_active_agent_is_rejected(db_session, factories, status):

    agent = _eligible_agent(factories, status=status)
    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "agent_inactive"
    assert exc_info.value.detail == status


def test_scan_job_for_an_ungranted_agent_is_rejected(db_session, factories):

    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=_AGENT_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "capability_disabled"


def test_scan_job_for_a_degraded_collector_is_rejected(db_session, factories):

    agent = _eligible_agent(factories, readiness="degraded")
    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "readiness_degraded"


def test_scan_job_with_an_out_of_scope_target_is_rejected(db_session, factories):

    agent = _eligible_agent(factories)
    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, target_cidr="192.168.50.0/24")
    assert exc_info.value.reason == "out_of_scope"
    assert exc_info.value.detail == "out_of_scope:192.168.50.0/24"


def test_scan_job_larger_than_the_address_ceiling_is_rejected(db_session, factories):

    agent = _eligible_agent(
        factories,
        interfaces=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}],
    )
    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, target_cidr="10.20.0.0/16")
    assert exc_info.value.reason == "address_limit_exceeded"
    assert exc_info.value.detail == "65536>1024"


def test_scan_job_naming_an_ungranted_port_is_rejected(db_session, factories):

    agent = _eligible_agent(factories)
    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, nmap_arguments="-p 9999")
    assert exc_info.value.reason == "port_not_granted"
    assert exc_info.value.detail == "9999"


def test_a_rejected_scan_job_writes_no_row(db_session, factories):
    from app.db.models import ScanJob

    agent = _eligible_agent(factories)
    before = db_session.query(ScanJob).count()
    with pytest.raises(discovery_admission.AgentExecutionLocationError):
        _create_agent_scan(db_session, agent, target_cidr="192.168.50.0/24")
    assert db_session.query(ScanJob).count() == before


def test_vlan_derived_targets_are_validated_too(db_session, factories):
    """VLAN ids resolve to CIDRs inside `create_scan_job`, so the indirection is
    not a way past the scope check."""
    from app.db.models import Network

    db_session.add(Network(name="vlan-908", cidr="192.168.61.0/24", vlan_id=908))
    db_session.flush()
    agent = _eligible_agent(factories)

    with pytest.raises(discovery_admission.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, target_cidr=None, vlan_ids=[908])
    assert exc_info.value.reason == "out_of_scope"


def test_a_server_scan_job_is_not_validated_against_any_agent(db_session, nmap_enabled, factories):
    """`scan_agent_id is None` is the existing server engine, which predates all of
    this and is untouched by it."""
    from app.services import discovery_service

    _eligible_agent(factories)
    job = discovery_service.create_scan_job(
        db_session, target_cidr="10.20.0.0/16", scan_types=["nmap"], nmap_arguments="-p 9999"
    )
    assert job.id is not None


# ---------------------------------------------------------------------------
# Reaching the agent through the API (Slice 4, §3 / Task 19 / Task 20)
# ---------------------------------------------------------------------------
#
# The two entry points a human can actually reach — "Run now" on a profile and
# the ad-hoc scan form — are the only way an agent scan is ever started by hand.
# Both have to carry the execution location all the way into `create_scan_job`,
# or an agent profile produces either a server-run job (plan §3 forbids the
# fallback: it silently changes the discovery vantage point) or, because D-6
# makes `["agent_connect"]` the only legal scan-type list on an agent, a hard
# failure from `validate_scan_types` that the generic handler renders as a 500.
#
# Both endpoints must also answer a refusal with Task 19's *structured* 422 —
# `{"reason", "detail", "message"}`, the same body `discovery_profiles_service`
# already returns on profile save — so the frontend switches on one closed
# vocabulary rather than two.

_SERVER_SUBNET = "192.168.70.0/24"


@pytest.fixture
def routed_jobs(monkeypatch, db_session):
    """Records which executor each job the API starts is handed to.

    Only `schedule_discovery_scan_job` — the *session-opening* wrapper — is
    replaced, and it is replaced with a call to the real `execute_scan_job`. The
    wrapper opens its own `SessionLocal`, which cannot see the SAVEPOINT this
    test's job was written inside, so the genuine router would find no row and
    every routing assertion would pass vacuously. The branch under test is still
    the shipped one.

    Both halves of the server executor are spied, as
    `tests/services/test_agent_discovery_dispatch.py` does: the phase split means
    a router that called `_scan_setup` instead of `run_scan_job` would look inert
    from the outside right up until it started sweeping the operator's network.
    """
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import agent_discovery, discovery_service

    agent_jobs: list[int] = []
    server_calls: list[str] = []
    started: list[asyncio.Future] = []

    async def _dispatch(db, job_id):
        agent_jobs.append(job_id)
        return True

    monkeypatch.setattr(agent_discovery, "dispatch_discovery_job", AsyncMock(side_effect=_dispatch))
    monkeypatch.setattr(
        discovery_service,
        "run_scan_job",
        AsyncMock(side_effect=lambda job_id: server_calls.append("run_scan_job")),
    )
    monkeypatch.setattr(
        discovery_service, "_scan_setup", lambda job_id: server_calls.append("_scan_setup")
    )

    def _schedule(job_id: int) -> None:
        started.append(
            asyncio.ensure_future(discovery_dispatch.execute_scan_job(db_session, job_id))
        )

    monkeypatch.setattr(discovery_dispatch, "schedule_discovery_scan_job", _schedule)

    async def drain() -> None:
        if started:
            await asyncio.gather(*started)

    return SimpleNamespace(agent=agent_jobs, server=server_calls, drain=drain)


def _scan_job_row(db_session, job_id):
    from app.db.models import ScanJob

    return db_session.get(ScanJob, job_id)


async def _create_profile(client, auth_headers, payload):
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_running_an_agent_profile_starts_an_agent_job_on_the_agent(
    client, auth_headers, db_session, factories, routed_jobs
):
    """ "Run now" on an agent profile is the manual half of D-6, and it is a 500
    the moment the endpoint drops `scan_agent_id`: `["agent_connect"]` with no
    agent is exactly what `validate_scan_types` refuses."""
    agent = _eligible_agent(factories)
    profile_id = await _create_profile(client, auth_headers, _agent_profile_payload(agent))

    resp = await client.post(f"{PROFILES_URL}/{profile_id}/run", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    await routed_jobs.drain()

    job = _scan_job_row(db_session, resp.json()["id"])
    assert job.scan_agent_id == agent.id
    assert job.source_type == "agent"
    assert routed_jobs.agent == [job.id]
    assert routed_jobs.server == []


@pytest.mark.asyncio
async def test_running_a_server_profile_still_starts_it_on_the_server(
    client, auth_headers, db_session, factories, nmap_enabled, routed_jobs
):
    """The branch has to be a branch: forwarding an agent onto every job would
    pass the assertion above and take server discovery with it."""
    profile_id = await _create_profile(
        client,
        auth_headers,
        {"name": "server-executed", "cidr": _SERVER_SUBNET, "scan_types": ["nmap"]},
    )

    resp = await client.post(f"{PROFILES_URL}/{profile_id}/run", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    await routed_jobs.drain()

    job = _scan_job_row(db_session, resp.json()["id"])
    assert job.scan_agent_id is None
    assert routed_jobs.agent == []
    assert routed_jobs.server == ["run_scan_job"]


@pytest.mark.asyncio
async def test_running_an_agent_profile_for_an_ineligible_agent_is_a_structured_422(
    client, auth_headers, db_session, factories, routed_jobs
):
    """A profile saved while its agent was eligible can be run after the agent is
    revoked, so the run endpoint owns a refusal of its own — and it has to be the
    same shape the save gave, not the 500 an unhandled `ValueError` becomes."""
    from app.db.models import ScanJob

    agent = _eligible_agent(factories)
    profile_id = await _create_profile(client, auth_headers, _agent_profile_payload(agent))
    before = db_session.query(ScanJob).count()
    agent.status = "revoked"
    db_session.flush()

    resp = await client.post(f"{PROFILES_URL}/{profile_id}/run", headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "agent_inactive"
    assert resp.json()["detail"]["detail"] == "revoked"
    assert db_session.query(ScanJob).count() == before
    assert routed_jobs.agent == [] and routed_jobs.server == []


@pytest.mark.asyncio
async def test_adhoc_scan_for_an_eligible_agent_starts_an_agent_job_on_the_agent(
    client, auth_headers, db_session, factories, routed_jobs
):
    """Task 19 names `POST /discovery/scan` explicitly. Without the forward, a
    fully eligible agent gets a bare 422 and no job at all."""
    agent = _eligible_agent(factories)

    resp = await client.post(
        SCAN_URL,
        json={
            "cidr": _AGENT_SUBNET,
            "scan_types": ["agent_connect"],
            "scan_agent_id": agent.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    await routed_jobs.drain()

    job = _scan_job_row(db_session, resp.json()["id"])
    assert job.scan_agent_id == agent.id
    assert job.source_type == "agent"
    assert routed_jobs.agent == [job.id]
    assert routed_jobs.server == []


@pytest.mark.asyncio
async def test_adhoc_scan_without_an_agent_still_starts_it_on_the_server(
    client, auth_headers, db_session, nmap_enabled, routed_jobs
):
    """The other side of the same branch, for the ad-hoc form."""
    resp = await client.post(
        SCAN_URL,
        json={"cidr": _SERVER_SUBNET, "scan_types": ["nmap"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    await routed_jobs.drain()

    job = _scan_job_row(db_session, resp.json()["id"])
    assert job.scan_agent_id is None
    assert routed_jobs.agent == []
    assert routed_jobs.server == ["run_scan_job"]


def _agent_for_reason(factories, reason):
    """The agent that produces exactly one §7 refusal, and the request that trips it.

    One agent per reason rather than one agent mutated per case, because the
    checks are ordered and a fixture missing two preconditions would report only
    the first — which is how a per-reason table stops distinguishing anything.
    """
    if reason == "capability_disabled":
        agent = factories.agent(status="active")
        factories.agent_network(agent, facts=_AGENT_INTERFACES)
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
        return agent, {}
    if reason == "readiness_degraded":
        return _eligible_agent(factories, readiness="degraded"), {}
    if reason == "out_of_scope":
        return _eligible_agent(factories), {"cidr": "192.168.50.0/24"}
    if reason == "address_limit_exceeded":
        agent = _eligible_agent(factories, interfaces=_OVERSIZED_INTERFACES)
        return agent, {"cidr": _OVERSIZED_SUBNET}
    if reason == "port_not_granted":
        return _eligible_agent(factories), {"nmap_arguments": "-p 9999"}
    return _eligible_agent(factories, status=reason), {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_reason", "expected_detail"),
    [
        ("pending", "agent_inactive", "pending"),
        ("rejected", "agent_inactive", "rejected"),
        ("revoked", "agent_inactive", "revoked"),
        ("capability_disabled", "capability_disabled", None),
        ("readiness_degraded", "readiness_degraded", None),
        ("out_of_scope", "out_of_scope", "out_of_scope:192.168.50.0/24"),
        ("address_limit_exceeded", "address_limit_exceeded", "65536>1024"),
        ("port_not_granted", "port_not_granted", "9999"),
    ],
)
async def test_adhoc_agent_scan_refusals_reach_the_caller_as_one_reason_vocabulary(
    client, auth_headers, db_session, factories, routed_jobs, case, expected_reason, expected_detail
):
    """Every §7 refusal, answered by `POST /discovery/scan` with the machine-readable
    `reason` Task 19 requires — the same body profile save already returns. A generic
    "Invalid scan request parameters." leaves the UI nothing to render and nothing to
    tell the operator to fix."""
    from app.db.models import ScanJob

    agent, extra = _agent_for_reason(factories, case)
    before = db_session.query(ScanJob).count()
    payload = {
        "cidr": _AGENT_SUBNET,
        "scan_types": ["agent_connect"],
        "scan_agent_id": agent.id,
    }
    payload.update(extra)

    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["reason"] == expected_reason
    if expected_detail is not None:
        assert detail["detail"] == expected_detail
    assert detail["message"]
    # No job, and nothing handed to either executor: a refusal is a refusal at
    # creation time, not a job that fails later.
    assert db_session.query(ScanJob).count() == before
    assert routed_jobs.agent == [] and routed_jobs.server == []


@pytest.mark.asyncio
async def test_adhoc_scan_still_answers_a_plain_bad_request_generically(
    client, auth_headers, db_session, factories, routed_jobs
):
    """The structured arm must not swallow the existing one: a `ValueError` that is
    not an execution-location refusal still gets the opaque 422, because those
    messages describe server internals rather than a rule the operator can act on."""
    resp = await client.post(
        SCAN_URL,
        json={"cidr": "10.99.0.0/24", "scan_types": ["nmap"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Invalid scan request parameters."
