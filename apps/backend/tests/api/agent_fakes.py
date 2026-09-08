"""Shared test doubles for the test_agents_api.py split family under
tests/api/.

Anything used by two or more of the split modules lives here and is
imported explicitly; a helper used by exactly one module lives in that
module instead. This file is not itself collected by pytest (its name
doesn't start with `test_`).
"""

import contextlib
from unittest.mock import AsyncMock

from sqlalchemy import event

REMOTE_PROBE_DEFAULT_CONFIG = {
    "max_concurrent": 20,
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "additional_hostnames": [],
}


# The registry default (`CAPABILITY_DEFINITIONS["local_discovery"]`), spelled out
# for the same reason: a silent change to the server-side defaults must fail
# loudly here rather than quietly ship a wider scan to every approved agent.
LOCAL_DISCOVERY_DEFAULT_CONFIG = {
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "max_addresses_per_job": 1024,
    "max_concurrent_hosts": 64,
    "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    "host_timeout_ms": 1500,
    "job_timeout_seconds": 300,
    "auto_discovery_paused": False,
}


@contextlib.contextmanager
def _capture_sql():
    """Record every statement the engine executes while the block is open."""
    from app.db.session import engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", _record)


_DISCOVERY_SUBNET = "10.30.40.0/24"
_DISCOVERY_INTERFACES = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.30.40.5/24"]}]


DISCOVERY_SUBNET_B = "10.30.41.0/24"


def _build_discovery_frames(monkeypatch) -> list[tuple[int, dict]]:
    """Every control frame these routes put on the wire.

    A plain builder rather than a `@pytest.fixture` itself: a fixture
    imported by name into another module for pytest's implicit
    injection-by-parameter-name reads, to static analysis, as an unused
    import shadowed by that same-named parameter -- ruff strips the
    import as dead (or flags the parameter as redefining it) on the next
    autofix pass. Each consuming module instead declares its own thin
    `discovery_frames` fixture that calls this.
    """
    from app.services import agent_registry

    frames: list[tuple[int, dict]] = []

    async def _spy(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=_spy))
    return frames


def _discovery_cancels(frames):
    from app.schemas.agent_frame import TYPE_DISCOVERY_CANCEL

    return [f["payload"] for _, f in frames if f["type"] == TYPE_DISCOVERY_CANCEL]


def _discovery_agent(factories, *, interfaces=None, **grant):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent, capability="local_discovery", enabled=True, config=grant.get("config", {})
    )
    # One `agent_networks` row per agent (`uq_agent_networks_agent_id`), so the
    # reported interfaces are chosen here rather than layered on afterwards.
    factories.agent_network(agent, facts=interfaces or _DISCOVERY_INTERFACES)
    factories.agent_capability_readiness(agent, collector="discovery.tcp", state="ready")
    return agent


def _live_dispatch(db_session, agent, **kwargs):
    import secrets
    from datetime import timedelta

    from app.core.time import utcnow, utcnow_iso
    from app.db.models import ScanJob
    from app.services.discovery_eligibility import derive_discovery_scope

    defaults = {
        "scan_agent_id": agent.id,
        "target_cidr": _DISCOVERY_SUBNET,
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


def _scheduled_profile_ids():
    from app.core.scheduler import get_scheduler

    return {
        int(job.id.removeprefix("discovery_profile_"))
        for job in get_scheduler().get_jobs()
        if job.id.startswith("discovery_profile_")
    }


def _agent_profile(db_session, agent, **kwargs):
    from app.core.time import utcnow_iso
    from app.db.models import DiscoveryProfile

    now = utcnow_iso()
    defaults = {
        "name": f"auto-{agent.id}",
        "cidr": _DISCOVERY_SUBNET,
        "normalized_cidr": _DISCOVERY_SUBNET,
        "scan_types": '["agent_connect"]',
        "scan_agent_id": agent.id,
        "managed_by": "system",
        "schedule_cron": "5 */6 * * *",
        "enabled": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    profile = DiscoveryProfile(**defaults)
    db_session.add(profile)
    db_session.flush()
    return profile


def _discovery_url(agent) -> str:
    return f"/api/v1/agents/{agent.id}/discovery"
