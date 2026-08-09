"""Execution location on the discovery profile service (Slice 4, D-7 and §3).

`scan_agent_id` says where a profile runs; `normalized_cidr` and `managed_by`
are the key the system-profile uniqueness rule is enforced on. Both of the
latter are server-derived — the point of those tests is that no request body
can reach them.

The second half of the file is plan §3's first checkpoint: a profile naming an
agent that could not run it is refused before anything is written, with a reason
from `discovery_eligibility`'s closed vocabulary.
"""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.db.models import DiscoveryProfile
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services import discovery_eligibility as elig
from app.services import discovery_profiles_service, discovery_service

ACTOR = "test-admin"


@pytest.fixture
def discovery_jobs():
    """Report registered discovery job ids, and clear them on teardown.

    The scheduler is process-global module state; a job left behind outlives
    the rolled-back DB row it names.
    """
    from app.core.scheduler import get_scheduler

    def ids() -> set[str]:
        return {job.id for job in get_scheduler().get_jobs()}

    yield ids
    for job in get_scheduler().get_jobs():
        if job.id.startswith("discovery_profile_"):
            job.remove()


# The one `agent_networks` report every agent below carries. Two interfaces
# because the table holds a single row per agent while these tests target two
# subnets, and both have to be in the derived scope for the profile to save.
_REPORTED_INTERFACES = [
    {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]},
    {"name": "eth1", "flags": ["broadcast", "up"], "addrs": ["10.77.0.5/24"]},
]


def _agent(factories, **grant):
    """An agent eligible to run the profiles these tests save (§3).

    Creation-time validation refuses an agent-targeted profile whose agent could
    not run it, so even a test that only cares where `scan_agent_id` is persisted
    has to build a *runnable* agent: the grant, the reported networks that put
    every target below in scope, and a fresh `discovery.tcp` readiness row.
    """
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True, **grant)
    factories.agent_network(agent, facts=_REPORTED_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    return agent


def _create(db_session, **overrides):
    payload = {
        "name": "profile-under-test",
        "cidr": "10.20.30.0/24",
        "scan_types": ["nmap"],
    }
    payload.update(overrides)
    return discovery_profiles_service.create_profile(
        db_session, DiscoveryProfileCreate(**payload), ACTOR
    )


def test_create_persists_scan_agent_id(db_session, factories):
    agent = _agent(factories)
    profile = _create(
        db_session,
        scan_types=["agent_connect"],
        scan_agent_id=agent.id,
    )
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id


def test_create_leaves_scan_agent_id_null_for_server_profiles(db_session):
    profile = _create(db_session)
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None


def test_create_derives_normalized_cidr_from_a_host_bearing_cidr(db_session):
    """`10.20.30.5/24` and `10.20.30.0/24` name the same segment."""
    profile = _create(db_session, cidr="10.20.30.5/24")
    row = db_session.get(DiscoveryProfile, profile.id)
    assert row.cidr == "10.20.30.5/24"
    assert row.normalized_cidr == "10.20.30.0/24"


def test_create_leaves_normalized_cidr_null_when_cidr_is_absent(db_session):
    profile = _create(db_session, cidr=None)
    assert db_session.get(DiscoveryProfile, profile.id).normalized_cidr is None


def test_create_leaves_normalized_cidr_null_when_cidr_is_not_a_network(db_session):
    """`cidr` is free text today; an unparseable one costs the key, not the row."""
    profile = _create(db_session, cidr="192.168.1.10-192.168.1.40")
    row = db_session.get(DiscoveryProfile, profile.id)
    assert row.id is not None
    assert row.normalized_cidr is None


def test_create_leaves_managed_by_null_for_user_profiles(db_session):
    profile = _create(db_session)
    assert db_session.get(DiscoveryProfile, profile.id).managed_by is None


def test_create_records_managed_by_for_server_callers(db_session):
    """Only an in-process caller — the bootstrap — may claim a profile."""
    profile = discovery_profiles_service.create_profile(
        db_session,
        DiscoveryProfileCreate(name="auto", cidr="10.9.0.0/24", scan_types=["nmap"]),
        ACTOR,
        managed_by="system",
    )
    assert db_session.get(DiscoveryProfile, profile.id).managed_by == "system"


def test_create_ignores_managed_by_in_the_request_payload(db_session):
    """`managed_by` is server-set only: the request schema must not carry it."""
    payload = DiscoveryProfileCreate(
        **{
            "name": "impostor",
            "cidr": "10.9.1.0/24",
            "scan_types": ["nmap"],
            "managed_by": "system",
        }
    )
    assert not hasattr(payload, "managed_by")
    profile = discovery_profiles_service.create_profile(db_session, payload, ACTOR)
    assert db_session.get(DiscoveryProfile, profile.id).managed_by is None


def test_create_ignores_normalized_cidr_in_the_request_payload(db_session):
    payload = DiscoveryProfileCreate(
        **{
            "name": "impostor-cidr",
            "cidr": "10.9.2.0/24",
            "scan_types": ["nmap"],
            "normalized_cidr": "172.16.0.0/12",
        }
    )
    profile = discovery_profiles_service.create_profile(db_session, payload, ACTOR)
    assert db_session.get(DiscoveryProfile, profile.id).normalized_cidr == "10.9.2.0/24"


def test_update_persists_scan_agent_id(db_session, factories):
    agent = _agent(factories)
    profile = _create(db_session)
    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate(scan_types=["agent_connect"], scan_agent_id=agent.id),
        ACTOR,
    )
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id


def test_update_recomputes_normalized_cidr_with_cidr(db_session):
    """A stale key would keep the uniqueness rule pointed at the old subnet."""
    profile = _create(db_session, cidr="10.20.30.0/24")
    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate(cidr="10.40.50.9/24"), ACTOR
    )
    row = db_session.get(DiscoveryProfile, profile.id)
    assert row.cidr == "10.40.50.9/24"
    assert row.normalized_cidr == "10.40.50.0/24"


def test_update_without_cidr_leaves_normalized_cidr_alone(db_session):
    profile = _create(db_session, cidr="10.20.30.0/24")
    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate(name="renamed"), ACTOR
    )
    assert db_session.get(DiscoveryProfile, profile.id).normalized_cidr == "10.20.30.0/24"


def test_update_ignores_managed_by_in_the_request_payload(db_session):
    profile = _create(db_session)
    payload = DiscoveryProfileUpdate(**{"name": "renamed", "managed_by": "system"})
    discovery_profiles_service.update_profile(db_session, profile.id, payload, ACTOR)
    assert db_session.get(DiscoveryProfile, profile.id).managed_by is None


def test_update_records_managed_by_for_server_callers(db_session):
    profile = _create(db_session)
    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate(name="adopted"),
        ACTOR,
        managed_by="system",
    )
    assert db_session.get(DiscoveryProfile, profile.id).managed_by == "system"


def test_server_derived_key_feeds_the_system_uniqueness_index(db_session, factories):
    """Two system profiles for one (agent, subnet) collide; a user profile does not.

    This is the whole reason `normalized_cidr` is derived rather than accepted:
    it is the index key from D-7.
    """
    agent = _agent(factories)
    common = {"scan_types": ["agent_connect"], "scan_agent_id": agent.id}
    discovery_profiles_service.create_profile(
        db_session,
        DiscoveryProfileCreate(name="auto-a", cidr="10.77.0.0/24", **common),
        ACTOR,
        managed_by="system",
    )
    # Same segment written differently — the raw `cidr` differs, the key does not.
    with pytest.raises(IntegrityError):
        discovery_profiles_service.create_profile(
            db_session,
            DiscoveryProfileCreate(name="auto-b", cidr="10.77.0.6/24", **common),
            ACTOR,
            managed_by="system",
        )
    db_session.rollback()

    user_profile = discovery_profiles_service.create_profile(
        db_session,
        DiscoveryProfileCreate(name="mine", cidr="10.77.0.0/24", **common),
        ACTOR,
    )
    assert db_session.get(DiscoveryProfile, user_profile.id).managed_by is None


def test_create_registers_the_profile_with_the_scheduler(db_session, factories, discovery_jobs):
    """Without this, DiscoveryStatusOut.next_scheduled — read off live APScheduler
    jobs — silently omits every agent-executed profile."""
    agent = _agent(factories)
    profile = _create(
        db_session,
        scan_types=["agent_connect"],
        scan_agent_id=agent.id,
        schedule_cron="7 */6 * * *",
        enabled=True,
    )
    assert f"discovery_profile_{profile.id}" in discovery_jobs()


# ── Creation-time validation of an agent-targeted profile (§3, §7) ────────────
#
# Plan §3 requires the same preconditions at profile save and at job creation, and
# §7 names four checkpoints in all. These are the first: a profile that names an
# agent which could not run it is refused with a 422 whose `reason` comes from
# `discovery_eligibility`'s closed vocabulary, so the frontend renders one set of
# strings wherever the answer is given. This is *in addition to* the dispatch-time
# re-check, never instead of it — a scope can change between the save and the job
# it eventually produces, which is exactly what the grant's version exists for.


def _rejection(exc_info) -> dict:
    """The structured 422 body a refusal carries."""
    assert exc_info.value.status_code == 422, exc_info.value.detail
    detail = exc_info.value.detail
    assert isinstance(detail, dict), detail
    return detail


def _agent_profile(db_session, agent, **overrides):
    payload = {"scan_types": ["agent_connect"], "scan_agent_id": agent.id}
    payload.update(overrides)
    return _create(db_session, **payload)


def test_an_eligible_agent_and_an_in_scope_target_saves(db_session, factories):
    """The happy path, first — every refusal below removes one of its conditions."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id


@pytest.mark.parametrize("status", ["pending", "rejected", "revoked"])
def test_a_non_active_agent_is_refused(db_session, factories, status):
    """§7: pending, rejected and revoked agents can never scan."""
    agent = factories.agent(status=status)
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent, facts=_REPORTED_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    detail = _rejection(exc_info)
    assert detail["reason"] == elig.REASON_AGENT_INACTIVE
    assert detail["detail"] == status


def test_an_ungranted_agent_is_refused(db_session, factories):
    agent = factories.agent(status="active")
    factories.agent_network(agent, facts=_REPORTED_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    assert _rejection(exc_info)["reason"] == elig.REASON_CAPABILITY_DISABLED


def test_degraded_collector_readiness_is_refused(db_session, factories):
    """A sweep that half-works reports *fewer hosts*, which nothing downstream can
    tell apart from a segment that really is that empty."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(agent, facts=_REPORTED_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="degraded")

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    assert _rejection(exc_info)["reason"] == elig.REASON_READINESS_DEGRADED


def test_a_target_outside_the_agents_scope_is_refused(db_session, factories):
    agent = _agent(factories)

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="192.168.50.0/24")

    detail = _rejection(exc_info)
    assert detail["reason"] == elig.REASON_OUT_OF_SCOPE
    # The evaluator's own reason travels through, so a refusal that is really
    # about prefix width is not reported as an unremarkable scope miss.
    assert detail["detail"] == "out_of_scope:192.168.50.0/24"


def test_a_target_larger_than_the_grants_address_ceiling_is_refused(db_session, factories):
    """The gap `MIN_SCOPE_PREFIX_V4 = 16` leaves open: a /16 is squarely in scope
    at the width limit and is still 65 536 addresses against a 1 024 ceiling."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    factories.agent_network(
        agent, facts=[{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}]
    )
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="10.20.0.0/16")

    detail = _rejection(exc_info)
    assert detail["reason"] == discovery_service.REASON_ADDRESS_LIMIT
    assert detail["detail"] == "65536>1024"


def test_a_port_outside_the_grant_is_refused(db_session, factories):
    agent = _agent(factories)

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr="10.20.30.0/24", nmap_arguments="-p 9999")

    detail = _rejection(exc_info)
    assert detail["reason"] == discovery_service.REASON_PORT_NOT_GRANTED
    assert detail["detail"] == "9999"


def test_a_granted_port_set_saves(db_session, factories):
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24", nmap_arguments="-p 22,443")
    assert db_session.get(DiscoveryProfile, profile.id).nmap_arguments == "-p 22,443"


def test_a_refused_profile_writes_no_row(db_session, factories):
    """Validation runs before the insert, so a refusal leaves nothing behind for
    the scheduler to pick up."""
    agent = _agent(factories)
    with pytest.raises(HTTPException):
        _agent_profile(db_session, agent, name="never-saved", cidr="192.168.50.0/24")
    assert (
        db_session.query(DiscoveryProfile).filter(DiscoveryProfile.name == "never-saved").count()
        == 0
    )


def test_a_server_profile_is_not_validated_against_any_agent(db_session):
    """`scan_agent_id is None` is the existing server engine and predates all of
    this: a /8 target with no agent is none of this gate's business."""
    profile = _create(db_session, cidr="10.0.0.0/8", nmap_arguments="-p 9999")
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None


def test_an_offline_agent_still_saves(db_session, factories):
    """D-5: an offline agent parks its job as `waiting_for_agent` and keeps it
    queued, so reachability is a scheduling condition. Refusing it here would make
    an agent unconfigurable from its first reboot onwards — no presence is
    registered anywhere in this module's tests, which is what makes the point."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id


def test_a_vlan_derived_target_is_validated_too(db_session, factories):
    """A VLAN resolves to CIDRs before it reaches an agent, so the indirection
    cannot be a way around the scope check."""
    from app.db.models import Network

    db_session.add(Network(name="vlan-909", cidr="192.168.60.0/24", vlan_id=909))
    db_session.flush()
    agent = _agent(factories)

    with pytest.raises(HTTPException) as exc_info:
        _agent_profile(db_session, agent, cidr=None, vlan_ids=[909])

    assert _rejection(exc_info)["reason"] == elig.REASON_OUT_OF_SCOPE


# ── The same gate on update ───────────────────────────────────────────────────


def test_repointing_a_profile_at_an_ineligible_agent_is_refused(db_session, factories):
    agent = factories.agent(status="active")  # no grant, no networks, no readiness
    profile = _create(db_session)

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session,
            profile.id,
            DiscoveryProfileUpdate(scan_types=["agent_connect"], scan_agent_id=agent.id),
            ACTOR,
        )

    assert _rejection(exc_info)["reason"] == elig.REASON_CAPABILITY_DISABLED
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None


def test_moving_an_agent_profile_to_an_out_of_scope_target_is_refused(db_session, factories):
    """The new `cidr` is judged against the agent already on the profile, so the
    two halves of the decision cannot be changed one at a time to get past it."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session, profile.id, DiscoveryProfileUpdate(cidr="192.168.50.0/24"), ACTOR
        )

    assert _rejection(exc_info)["reason"] == elig.REASON_OUT_OF_SCOPE
    assert db_session.get(DiscoveryProfile, profile.id).cidr == "10.20.30.0/24"


def test_an_in_scope_move_is_allowed(db_session, factories):
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate(cidr="10.77.0.0/24"), ACTOR
    )
    assert db_session.get(DiscoveryProfile, profile.id).normalized_cidr == "10.77.0.0/24"


def test_disabling_a_profile_whose_agent_went_away_still_works(db_session, factories):
    """The refusal must not lock an operator out of the one edit that stops the
    profile. D-14 makes disabling a profile a *cancellation* trigger, so it has to
    remain reachable exactly when the agent has become ineligible — a revoked
    agent is the case that matters and is where an unconditional re-check would
    strand every profile naming it."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    agent.status = "revoked"
    db_session.flush()

    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate(enabled=False), ACTOR
    )

    assert db_session.get(DiscoveryProfile, profile.id).enabled == 0


def test_renaming_a_profile_whose_agent_went_away_still_works(db_session, factories):
    """Same rule stated for the other unrelated edit: nothing about a name or a
    cron touches the execution location, so nothing about it is re-decided."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    agent.status = "revoked"
    db_session.flush()

    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate(name="renamed"), ACTOR
    )

    assert db_session.get(DiscoveryProfile, profile.id).name == "renamed"


def test_an_update_that_names_ports_is_validated(db_session, factories):
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session, profile.id, DiscoveryProfileUpdate(nmap_arguments="-p 9999"), ACTOR
        )

    assert _rejection(exc_info)["reason"] == discovery_service.REASON_PORT_NOT_GRANTED


# ── The scan-type vocabulary is judged against the merged profile (§3, D-6) ───
#
# `scan_types` and `scan_agent_id` are two halves of one decision: which types are
# legal is entirely a function of where the profile executes. A PATCH names either
# half on its own, so both have to be read as the profile *would be*. Judged
# against the payload alone — where an unset `scan_agent_id` reads as "the server"
# — a server-only type could be moved onto an agent profile one field at a time,
# and the row that produced was unfixable and undefined at dispatch.


def _stored_scan_types(db_session, profile_id: int) -> list[str]:
    return json.loads(db_session.get(DiscoveryProfile, profile_id).scan_types)


def test_patch_cannot_move_a_server_scan_type_onto_an_agent_profile(db_session, factories):
    """The payload names no agent, but the stored profile has one."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session,
            profile.id,
            DiscoveryProfileUpdate.model_validate({"scan_types": ["nmap"]}),
            ACTOR,
        )

    detail = _rejection(exc_info)
    assert detail["reason"] == discovery_profiles_service.REASON_SCAN_TYPE_INVALID
    # The offending type is named, or the operator cannot tell which one to drop.
    assert "nmap" in detail["message"]
    assert _stored_scan_types(db_session, profile.id) == ["agent_connect"]


def test_patch_cannot_strip_the_agent_from_an_agent_only_profile(db_session, factories):
    """The mirror image: the payload names no scan types, but the stored ones
    require the agent this PATCH removes."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session,
            profile.id,
            DiscoveryProfileUpdate.model_validate({"scan_agent_id": None}),
            ACTOR,
        )

    assert _rejection(exc_info)["reason"] == discovery_profiles_service.REASON_SCAN_TYPE_INVALID
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id


def test_patch_cannot_hand_a_server_only_profile_to_an_agent(db_session, factories):
    """Adding an agent to a profile whose stored types only the server can run."""
    profile = _create(db_session)  # scan_types ["nmap"], no agent
    agent = _agent(factories)

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session,
            profile.id,
            DiscoveryProfileUpdate.model_validate({"scan_agent_id": agent.id}),
            ACTOR,
        )

    assert _rejection(exc_info)["reason"] == discovery_profiles_service.REASON_SCAN_TYPE_INVALID
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None


def test_patch_moving_both_halves_to_an_agent_at_once_is_allowed(db_session, factories):
    """Consistent, so nothing is refused: this is how a profile is legitimately
    handed to an agent."""
    profile = _create(db_session)
    agent = _agent(factories)

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate(
            {"scan_types": ["agent_connect"], "scan_agent_id": agent.id}
        ),
        ACTOR,
    )

    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id == agent.id
    assert _stored_scan_types(db_session, profile.id) == ["agent_connect"]


def test_patch_moving_both_halves_back_to_the_server_at_once_is_allowed(db_session, factories):
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"scan_types": ["nmap"], "scan_agent_id": None}),
        ACTOR,
    )

    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None
    assert _stored_scan_types(db_session, profile.id) == ["nmap"]


def test_patch_moving_both_halves_inconsistently_is_refused(db_session, factories):
    """Both fields in one payload, contradicting each other."""
    profile = _create(db_session)
    agent = _agent(factories)

    with pytest.raises(HTTPException) as exc_info:
        discovery_profiles_service.update_profile(
            db_session,
            profile.id,
            DiscoveryProfileUpdate.model_validate(
                {"scan_types": ["nmap"], "scan_agent_id": agent.id}
            ),
            ACTOR,
        )

    assert _rejection(exc_info)["reason"] == discovery_profiles_service.REASON_SCAN_TYPE_INVALID
    assert db_session.get(DiscoveryProfile, profile.id).scan_agent_id is None


def test_patch_resending_the_agent_scan_type_without_the_agent_id_is_allowed(db_session, factories):
    """The edit form posts `scan_types` on every save and `scan_agent_id` only
    when it changes. Judged against the payload alone that legitimate no-op reads
    as "agent_connect with no agent" and is refused; judged against the merged
    profile it is what it is — unchanged."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"scan_types": ["agent_connect"]}),
        ACTOR,
    )

    assert _stored_scan_types(db_session, profile.id) == ["agent_connect"]


def test_patch_naming_neither_half_does_not_re_judge_the_stored_scan_types(db_session):
    """D-6 makes the vocabulary write-only: a row predating it may hold any string
    at all. An edit that moves the *target* is not an edit to the vocabulary, so a
    legacy row has to stay editable."""
    profile = _create(db_session)
    db_session.get(DiscoveryProfile, profile.id).scan_types = json.dumps(["legacy_thing"])
    db_session.flush()

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"cidr": "10.77.0.0/24"}),
        ACTOR,
    )

    row = db_session.get(DiscoveryProfile, profile.id)
    assert row.normalized_cidr == "10.77.0.0/24"
    assert json.loads(row.scan_types) == ["legacy_thing"]


def test_a_row_already_broken_by_the_missing_check_stays_repairable(db_session, factories):
    """Rows written before the merged check could hold a server-only type on an
    agent. The check must not make them uneditable: an unrelated edit still goes
    through, and one PATCH of either half puts the row back in a legal state."""
    agent = _agent(factories)
    profile = _agent_profile(db_session, agent, cidr="10.20.30.0/24")
    db_session.get(DiscoveryProfile, profile.id).scan_types = json.dumps(["nmap"])
    db_session.flush()

    discovery_profiles_service.update_profile(
        db_session, profile.id, DiscoveryProfileUpdate.model_validate({"name": "renamed"}), ACTOR
    )
    assert db_session.get(DiscoveryProfile, profile.id).name == "renamed"

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"scan_types": ["agent_connect"]}),
        ACTOR,
    )
    assert _stored_scan_types(db_session, profile.id) == ["agent_connect"]


def test_patch_stores_the_normalized_scan_type_list(db_session):
    """Dedupe survives the move of the check out of the schema: `discovery_service`
    compares the stored list by equality, so a repeated entry would change how the
    profile executes."""
    profile = _create(db_session)

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"scan_types": ["nmap", "arp", "nmap"]}),
        ACTOR,
    )

    assert _stored_scan_types(db_session, profile.id) == ["nmap", "arp"]


def test_patch_with_an_explicit_null_scan_types_leaves_the_stored_list_alone(db_session):
    """`null` is "leave it alone", not a value: writing it would put the string
    "null" in the column and every later read of the profile would fail."""
    profile = _create(db_session)

    discovery_profiles_service.update_profile(
        db_session,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"scan_types": None, "name": "renamed"}),
        ACTOR,
    )

    row = db_session.get(DiscoveryProfile, profile.id)
    assert row.name == "renamed"
    assert json.loads(row.scan_types) == ["nmap"]
