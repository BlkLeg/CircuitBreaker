"""Shared test doubles for tests/discovery/ — the discovery scan/profile API
suite split out of the former tests/test_discovery.py.

Anything used by two or more modules in this package lives here and is
imported explicitly; a helper used by exactly one module lives in that module
instead. The one shared pytest fixture (`cancel_frames`) lives in this
package's own conftest.py rather than here — see that file for why.
"""

SCAN_URL = "/api/v1/discovery/scan"
JOBS_URL = "/api/v1/discovery/jobs"
PROFILES_URL = "/api/v1/discovery/profiles"

_AGENT_SUBNET = "10.20.30.0/24"
_AGENT_INTERFACES = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.30.5/24"]}]
# One address inside `_AGENT_SUBNET`, for the findings a closed dispatch must refuse.
_AGENT_HOST = "10.20.30.77"

# Larger than the granted `max_addresses_per_job` default of 1024, and matched by
# the interface the fixture reports, so scope passes and only the ceiling refuses.
_OVERSIZED_SUBNET = "10.20.0.0/16"
_OVERSIZED_INTERFACES = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.20.0.5/16"]}]


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


def _eligible_agent(
    factories, *, status: str = "active", interfaces=None, readiness="ready", **agent_kwargs
):
    """An agent that satisfies every §3 precondition — tests remove one at a time."""
    agent = factories.agent(status=status, **agent_kwargs)
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


def _agent_profile_row(db_session, agent, **kwargs):
    from app.core.time import utcnow_iso
    from app.db.models import DiscoveryProfile

    now = utcnow_iso()
    defaults = {
        "name": "held-subnet",
        "cidr": _AGENT_SUBNET,
        "normalized_cidr": _AGENT_SUBNET,
        "scan_types": '["agent_connect"]',
        "scan_agent_id": agent.id,
        "managed_by": "system",
        "schedule_cron": "0 */6 * * *",
        "enabled": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    profile = DiscoveryProfile(**defaults)
    db_session.add(profile)
    db_session.flush()
    return profile


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
