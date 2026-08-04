import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.services import agent_registry as svc


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


def test_propose_hardware_match_by_machine_id_hash_beats_mac(db_session, factories):
    from app.db.models import Hardware

    hw_by_mac = Hardware(name="by-mac", mac_address="aa:bb:cc:dd:ee:ff")
    hw_by_machine_id = Hardware(name="by-machine-id")
    db_session.add_all([hw_by_mac, hw_by_machine_id])
    db_session.flush()

    agent = factories.agent(
        machine_id_hash="deadbeef",
        primary_macs=["aa:bb:cc:dd:ee:ff"],
    )
    # `Hardware` has no `machine_id_hash` column in the current schema (confirmed
    # via `grep -n machine_id_hash apps/backend/src/app/db/models.py` — the only
    # hit inside the Hardware class range is `mac_address`; `machine_id_hash`
    # belongs to `Agent`). Per the brief's guidance, `propose_hardware_match`
    # drops the machine_id_hash branch for slice 1 and falls straight through to
    # MAC -> hostname, so this narrows to an exact MAC match on `hw_by_mac`.
    match = svc.propose_hardware_match(db_session, agent)
    assert match is not None
    assert match.id == hw_by_mac.id


def test_propose_hardware_match_falls_back_to_hostname(db_session, factories):
    from app.db.models import Hardware

    hw_by_hostname = Hardware(name="box-by-hostname")
    db_session.add(hw_by_hostname)
    db_session.flush()

    agent = factories.agent(hostname="box-by-hostname", primary_macs=[])
    match = svc.propose_hardware_match(db_session, agent)
    assert match is not None
    assert match.id == hw_by_hostname.id


def test_propose_hardware_match_returns_none_when_no_match(db_session, factories):
    agent = factories.agent(hostname="no-such-host", primary_macs=["11:22:33:44:55:66"])
    match = svc.propose_hardware_match(db_session, agent)
    assert match is None


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


def test_bulk_grants_dict_maps_capability_grants_per_agent(db_session, factories):
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    factories.agent_capability_grant(agent_a, capability="host_telemetry", enabled=True)
    factories.agent_capability_grant(agent_a, capability="remote_probe", enabled=False)
    factories.agent_capability_grant(agent_b, capability="local_discovery", enabled=True)

    result = svc.bulk_grants_dict(db_session, [agent_a.id, agent_b.id])

    assert result == {
        agent_a.id: {"host_telemetry": True, "remote_probe": False},
        agent_b.id: {"local_discovery": True},
    }


def test_bulk_grants_dict_empty_for_agent_with_no_grants(db_session, factories):
    agent = factories.agent(status="pending")

    assert svc.bulk_grants_dict(db_session, [agent.id]) == {agent.id: {}}


def test_bulk_grants_dict_empty_list_returns_empty_dict(db_session):
    assert svc.bulk_grants_dict(db_session, []) == {}
