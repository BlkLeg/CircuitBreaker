"""Execution-location columns on the discovery profile service (Slice 4, D-7).

`scan_agent_id` says where a profile runs; `normalized_cidr` and `managed_by`
are the key the system-profile uniqueness rule is enforced on. Both of the
latter are server-derived — the point of these tests is that no request body
can reach them.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import DiscoveryProfile
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services import discovery_profiles_service

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


def _agent(factories):
    return factories.agent(status="active")


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
