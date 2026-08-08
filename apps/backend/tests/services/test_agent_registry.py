import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from app.services import agent_registry as svc

# The registry default (`CAPABILITY_DEFINITIONS["remote_probe"]`), spelled out
# so a silent change to the server-side defaults fails this test loudly.
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


def test_create_pending_agent_defaults_to_pending_status(db_session):
    agent = svc.create_pending_agent(
        db_session,
        device_pk="ab" * 32,
        fingerprint="cd" * 16,
        hostname="box1",
        machine_id_hash=None,
        os="linux",
        os_version="6.1",
        arch="amd64",
        agent_version="0.1.0",
        primary_macs=["aa:bb:cc:dd:ee:ff"],
        reported_ip="10.0.0.5",
    )
    assert agent.status == "pending"
    assert agent.id is not None


def test_approve_agent_applies_default_capability_grants(db_session, factories):
    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")

    approved = svc.approve_agent(db_session, agent.id, approving_user_id=admin.id)

    assert approved.status == "active"
    assert approved.approved_by_user_id == admin.id

    from app.db.models import AgentCapabilityGrant

    grants = {
        g.capability: g.enabled
        for g in db_session.query(AgentCapabilityGrant).filter_by(agent_id=agent.id).all()
    }
    assert grants == svc.DEFAULT_CAPABILITY_GRANTS


def test_approve_agent_honors_capability_overrides(db_session, factories):
    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")

    svc.approve_agent(
        db_session,
        agent.id,
        approving_user_id=admin.id,
        capability_overrides={"remote_probe": True},
    )

    from app.db.models import AgentCapabilityGrant

    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="remote_probe")
        .one()
    )
    assert grant.enabled is True


def test_boolean_override_still_receives_the_capability_default_config(
    db_session, factories, monkeypatch
):
    """Task 14: a bare-boolean grant is where `normalize_grant` injects the
    registry's default config. Before Task 14 only `host_telemetry` had that
    branch, so the moment any other capability grew defaults, approving with
    `{"remote_probe": True}` would have persisted `{}` — the exact defect
    slice 3 would otherwise inherit."""
    from app.db.models import AgentCapabilityGrant
    from app.services import agent_capabilities

    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")
    svc.approve_agent(
        db_session,
        agent.id,
        approving_user_id=admin.id,
        capability_overrides={"host_telemetry": True},
    )
    host = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="host_telemetry")
        .one()
    )
    assert host.config == dict(
        agent_capabilities.CAPABILITY_DEFINITIONS["host_telemetry"].default_config
    )
    assert len(host.config) == 7

    probe_default = {"max_concurrent": 4, "scope_mode": "direct_private"}
    monkeypatch.setitem(
        agent_capabilities.CAPABILITY_DEFINITIONS,
        "remote_probe",
        agent_capabilities.CapabilityDefinition(
            name="remote_probe",
            default_enabled=True,
            default_config=probe_default,
            normalize=lambda config: dict(config),
        ),
    )
    other = factories.agent(status="pending")
    svc.approve_agent(
        db_session,
        other.id,
        approving_user_id=admin.id,
        capability_overrides={"remote_probe": True},
    )
    probe = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=other.id, capability="remote_probe")
        .one()
    )
    assert probe.config == probe_default


def test_new_registry_entry_is_not_backfilled_onto_already_approved_agents(
    db_session, factories, monkeypatch
):
    """Global Constraint: "Upgrades never silently enable a new capability on an
    already-approved agent." `default_enabled` is consulted ONLY by
    `approve_agent`; a capability with no `agent_capability_grants` row is
    denied everywhere and no read path falls back to the registry default.

    THIS TEST MUST NEVER BE DELETED.
    """
    from app.services import agent_capabilities

    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")
    svc.approve_agent(db_session, agent.id, approving_user_id=admin.id)

    monkeypatch.setitem(
        agent_capabilities.CAPABILITY_DEFINITIONS,
        "fourth",
        agent_capabilities.CapabilityDefinition(
            name="fourth",
            default_enabled=True,
            default_config={},
            normalize=lambda config: dict(config),
        ),
    )

    structured = svc.structured_grants_dict(db_session, agent.id)
    assert set(structured) == {"host_telemetry", "remote_probe", "local_discovery"}
    assert "fourth" not in structured
    assert svc.grants_dict(db_session, agent.id).get("fourth", False) is False
    assert "fourth" not in svc.bulk_structured_grants_dict(db_session, [agent.id])[agent.id]


def test_revoke_agent_records_reason_and_actor(db_session, factories):
    agent = factories.agent(status="active")
    admin = factories.user(role="admin")

    revoked = svc.revoke_agent(db_session, agent.id, actor_user_id=admin.id, reason="lost device")

    assert revoked.status == "revoked"
    assert revoked.revoke_reason == "lost device"
    assert revoked.revoked_by_user_id == admin.id


def test_record_event_persists_detail(db_session, factories):
    agent = factories.agent()
    event = svc.record_event(
        db_session, agent.id, "capability_violation", detail={"type": "probe.result"}
    )
    assert event.event_type == "capability_violation"
    assert event.detail == {"type": "probe.result"}


def test_propose_hardware_match_by_machine_id_hash_beats_mac_and_hostname(db_session, factories):
    """Descending-confidence match order per spec §3.3: machine_id_hash -> MAC
    -> hostname. `Hardware.machine_id_hash` (Task 16) lets this resolve the
    strongest signal first even when a weaker MAC/hostname match also exists."""
    from app.db.models import Hardware

    hw_by_hostname = Hardware(name="by-hostname", hostname="box1")
    hw_by_mac = Hardware(name="by-mac", mac_address="aa:bb:cc:dd:ee:ff")
    hw_by_machine_id = Hardware(name="by-machine-id", machine_id_hash="deadbeef")
    db_session.add_all([hw_by_hostname, hw_by_mac, hw_by_machine_id])
    db_session.flush()

    agent = factories.agent(
        hostname="box1",
        machine_id_hash="deadbeef",
        primary_macs=["aa:bb:cc:dd:ee:ff"],
    )
    match = svc.propose_hardware_match(db_session, agent)
    assert match is not None
    assert match.id == hw_by_machine_id.id


def test_propose_hardware_match_mac_beats_hostname_when_no_machine_id_match(db_session, factories):
    from app.db.models import Hardware

    hw_by_hostname = Hardware(name="by-hostname", hostname="box1")
    hw_by_mac = Hardware(name="by-mac", mac_address="aa:bb:cc:dd:ee:ff")
    db_session.add_all([hw_by_hostname, hw_by_mac])
    db_session.flush()

    agent = factories.agent(
        hostname="box1",
        machine_id_hash="no-such-hash",
        primary_macs=["aa:bb:cc:dd:ee:ff"],
    )
    match = svc.propose_hardware_match(db_session, agent)
    assert match is not None
    assert match.id == hw_by_mac.id


def test_propose_hardware_match_falls_back_to_hostname(db_session, factories):
    from app.db.models import Hardware

    hw_by_hostname = Hardware(name="box-by-hostname")
    db_session.add(hw_by_hostname)
    db_session.flush()

    agent = factories.agent(hostname="box-by-hostname", primary_macs=[], machine_id_hash=None)
    match = svc.propose_hardware_match(db_session, agent)
    assert match is not None
    assert match.id == hw_by_hostname.id


def test_propose_hardware_match_returns_none_when_no_match(db_session, factories):
    agent = factories.agent(
        hostname="no-such-host", primary_macs=["11:22:33:44:55:66"], machine_id_hash=None
    )
    match = svc.propose_hardware_match(db_session, agent)
    assert match is None


def test_has_duplicate_machine_id_true_when_another_agent_shares_hash(db_session, factories):
    factories.agent(machine_id_hash="shared-hash")
    agent = factories.agent(machine_id_hash="shared-hash")

    assert svc.has_duplicate_machine_id(db_session, agent) is True


def test_has_duplicate_machine_id_false_when_unique(db_session, factories):
    agent = factories.agent(machine_id_hash="unique-hash")

    assert svc.has_duplicate_machine_id(db_session, agent) is False


def test_has_duplicate_machine_id_false_when_agent_has_no_hash(db_session, factories):
    agent = factories.agent(machine_id_hash=None)

    assert svc.has_duplicate_machine_id(db_session, agent) is False


def test_grants_dict_reduces_grants_to_capability_bool_map(db_session, factories):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    db_session.flush()

    result = svc.grants_dict(db_session, agent.id)

    assert result == {"host_telemetry": True, "remote_probe": False}


def test_grants_dict_empty_for_agent_with_no_grants(db_session, factories):
    agent = factories.agent(status="pending")
    assert svc.grants_dict(db_session, agent.id) == {}


@pytest.mark.asyncio
async def test_mark_presence_connected_writes_redis_with_ttl(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.mark_presence_connected(agent_id=5, worker="worker-1")

    redis_client.setex.assert_called_once()
    key, ttl, payload = redis_client.setex.call_args[0]
    assert key == "agent:presence:5"
    assert ttl == 60
    assert json.loads(payload)["worker"] == "worker-1"


@pytest.mark.asyncio
async def test_mark_presence_disconnected_deletes_redis_key(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.mark_presence_disconnected(agent_id=5)

    redis_client.delete.assert_called_once_with("agent:presence:5")


@pytest.mark.asyncio
async def test_is_agent_online_reflects_redis_key_presence(monkeypatch):
    redis_client = AsyncMock()
    redis_client.exists.return_value = 1
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    assert await svc.is_agent_online(5) is True
    redis_client.exists.assert_called_once_with("agent:presence:5")


@pytest.mark.asyncio
async def test_refresh_presence_heartbeat_throttles_postgres_write(
    db_session, factories, monkeypatch
):
    from app.core.time import utcnow

    agent = factories.agent(status="active", last_seen_at=utcnow())
    db_session.flush()
    original_last_seen = agent.last_seen_at

    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.refresh_presence_heartbeat(db_session, agent.id, worker="worker-1")

    redis_client.setex.assert_called_once()
    assert agent.last_seen_at == original_last_seen  # throttled — no write within 60s


# ── Task 12: bulk presence / bulk grants (fleet REST endpoint) ──────────────


@pytest.mark.asyncio
async def test_bulk_presence_reports_online_with_connected_since_for_present_keys(monkeypatch):
    connected_at = "2026-08-04T10:00:00+00:00"
    redis_client = AsyncMock()

    async def fake_mget(keys):
        store = {"agent:presence:5": json.dumps({"connected_at": connected_at, "worker": "w1"})}
        return [store.get(k) for k in keys]

    redis_client.mget.side_effect = fake_mget
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    result = await svc.bulk_presence([5])

    assert result == {5: {"online": True, "connected_since": datetime.fromisoformat(connected_at)}}


@pytest.mark.asyncio
async def test_bulk_presence_reports_offline_for_missing_or_ttl_expired_keys(monkeypatch):
    redis_client = AsyncMock()
    redis_client.mget.side_effect = lambda keys: [None for _ in keys]
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    result = await svc.bulk_presence([5, 6])

    assert result == {
        5: {"online": False, "connected_since": None},
        6: {"online": False, "connected_since": None},
    }


@pytest.mark.asyncio
async def test_bulk_presence_uses_single_mget_call_not_n_plus_1(monkeypatch):
    redis_client = AsyncMock()
    redis_client.mget.side_effect = lambda keys: [None for _ in keys]
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.bulk_presence([1, 2, 3, 4])

    redis_client.mget.assert_called_once()
    (keys,), _kwargs = redis_client.mget.call_args
    assert set(keys) == {
        "agent:presence:1",
        "agent:presence:2",
        "agent:presence:3",
        "agent:presence:4",
    }
    redis_client.get.assert_not_called()
    redis_client.exists.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_presence_all_offline_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    result = await svc.bulk_presence([5, 6])

    assert result == {
        5: {"online": False, "connected_since": None},
        6: {"online": False, "connected_since": None},
    }


@pytest.mark.asyncio
async def test_bulk_presence_empty_input_returns_empty_dict_without_calling_redis(monkeypatch):
    get_redis = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", get_redis)

    result = await svc.bulk_presence([])

    assert result == {}
    get_redis.assert_not_called()


def test_bulk_structured_grants_dict_maps_capability_grants_per_agent(db_session, factories):
    """Task 15 / D-11: the bulk read emits the canonical {enabled, config} shape,
    identical to `structured_grants_dict`, so `/agents/presence` and
    `/agents/{id}` cannot drift."""
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    factories.agent_capability_grant(
        agent_a, capability="host_telemetry", enabled=True, config={"interval_s": 90}
    )
    factories.agent_capability_grant(agent_a, capability="remote_probe", enabled=False)
    factories.agent_capability_grant(agent_b, capability="local_discovery", enabled=True)

    result = svc.bulk_structured_grants_dict(db_session, [agent_a.id, agent_b.id])

    assert result == {
        agent_a.id: svc.structured_grants_dict(db_session, agent_a.id),
        agent_b.id: svc.structured_grants_dict(db_session, agent_b.id),
    }
    assert result[agent_a.id]["host_telemetry"]["config"]["interval_s"] == 90
    # A grant row stored with no config still reads back the registry defaults,
    # which is why `remote_probe` gaining a real schema needed no migration.
    assert result[agent_a.id]["remote_probe"] == {
        "enabled": False,
        "config": REMOTE_PROBE_DEFAULT_CONFIG,
    }
    assert result[agent_b.id]["local_discovery"] == {
        "enabled": True,
        "config": LOCAL_DISCOVERY_DEFAULT_CONFIG,
    }


def test_bulk_structured_grants_dict_empty_for_agent_with_no_grants(db_session, factories):
    agent = factories.agent(status="pending")

    assert svc.bulk_structured_grants_dict(db_session, [agent.id]) == {agent.id: {}}


def test_bulk_structured_grants_dict_empty_list_returns_empty_dict(db_session):
    assert svc.bulk_structured_grants_dict(db_session, []) == {}


def test_bulk_structured_grants_dict_renders_unregistered_capability_verbatim(
    db_session, factories
):
    """A grant row naming a capability this build's registry does not declare
    must render with its own config, not raise a KeyError that 500s the fleet."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent, capability="legacy_thing", enabled=True, config={"whatever": 1}
    )

    result = svc.bulk_structured_grants_dict(db_session, [agent.id])

    assert result[agent.id]["legacy_thing"] == {"enabled": True, "config": {"whatever": 1}}
    single = svc.structured_grants_dict(db_session, agent.id)
    assert single["legacy_thing"] == result[agent.id]["legacy_thing"]


def test_bulk_structured_grants_dict_issues_one_query_for_the_whole_fleet(db_session, factories):
    """Task 15: canonicalizing the shape must not reintroduce an N+1."""
    agent_ids = []
    for _ in range(20):
        agent = factories.agent(status="active")
        factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
        agent_ids.append(agent.id)
    db_session.flush()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "agent_capability_grants" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "after_cursor_execute", _record)
    try:
        result = svc.bulk_structured_grants_dict(db_session, agent_ids)
    finally:
        event.remove(db_session.get_bind(), "after_cursor_execute", _record)

    assert set(result) == set(agent_ids)
    assert len(statements) == 1, statements


def test_record_spool_stats_writes_the_three_columns_on_first_report(db_session, factories):
    """NULL means "never reported" (an agent predating spool reporting); a
    recorded 0 means "reported, empty". The first report is what crosses that
    boundary."""
    agent = factories.agent(status="active")
    assert agent.spool_depth is None
    assert agent.spool_bytes is None
    assert agent.spool_reported_at is None

    wrote = svc.record_spool_stats(agent, 7, 8192)

    assert wrote is True
    assert agent.spool_depth == 7
    assert agent.spool_bytes == 8192
    assert agent.spool_reported_at is not None


def test_record_spool_stats_records_an_explicit_zero_backlog(db_session, factories):
    """A drained spool must be persisted as 0, not left NULL — that write is
    what clears the Agent Detail catch-up indicator."""
    agent = factories.agent(status="active")
    svc.record_spool_stats(agent, 7, 8192)

    wrote = svc.record_spool_stats(agent, 0, 0)

    assert wrote is True
    assert agent.spool_depth == 0
    assert agent.spool_bytes == 0


def test_unchanged_spool_stats_do_not_rewrite_the_row(db_session, factories):
    """Heartbeats arrive every 20s per agent, and the steady state is
    "depth 0, unchanged". Re-stamping the row on every one of them would be
    a fleet-wide UPDATE storm for no new information."""
    agent = factories.agent(status="active")
    assert svc.record_spool_stats(agent, 0, 0) is True
    db_session.commit()
    first_reported_at = agent.spool_reported_at

    wrote = svc.record_spool_stats(agent, 0, 0)

    assert wrote is False
    assert agent.spool_reported_at == first_reported_at
    assert agent.spool_depth == 0
    assert agent.spool_bytes == 0


def test_record_spool_stats_with_unknown_size_leaves_the_byte_column_alone(db_session, factories):
    """`hello` reports `spool_depth` but has no `spool_bytes` field, so its
    caller passes None — "unknown", not "zero"."""
    agent = factories.agent(status="active")
    svc.record_spool_stats(agent, 7, 8192)

    wrote = svc.record_spool_stats(agent, 3, None)

    assert wrote is True
    assert agent.spool_depth == 3
    assert agent.spool_bytes == 8192


def test_update_hello_metadata_persists_a_reported_spool_depth(db_session, factories):
    from app.schemas.agent_frame import HelloPayload

    agent = factories.agent(status="active")

    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"spool_depth": 3}))

    assert agent.spool_depth == 3
    assert agent.spool_reported_at is not None


def test_update_hello_metadata_leaves_spool_columns_null_when_omitted(db_session, factories):
    """Presence, not truthiness: an old-shaped hello omits `spool_depth`
    entirely and must not have a 0 invented for it."""
    from app.schemas.agent_frame import HelloPayload

    agent = factories.agent(status="active")

    svc.update_hello_metadata(db_session, agent, HelloPayload.model_validate({"os": "linux"}))

    assert agent.spool_depth is None
    assert agent.spool_bytes is None
    assert agent.spool_reported_at is None
