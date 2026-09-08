"""Task 9/10/11 end-to-end: a capabilities.set or disconnect frame published from
another worker (or by the real revoke/reject/capabilities-PUT REST endpoints)
reaches an already-connected agent immediately, and the durable fallback -- a
fresh hello.ack always carries the complete current grant set even when no push
was ever delivered.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import time

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
    _FakeTTLRedis,
    _login_admin,
    _receive_bytes_with_timeout,
    _send_hello,
)
from tests.helpers.agent_noise_client import TestNoiseInitiator

# Task 21 fix round (Important #2): every test in this file drives a real
# /link WS connection, which now runs through check_and_record_ws_attempt
# before any Noise handshake byte is processed — it fails closed if Redis
# is unreachable. Without this, every pre-existing test here that doesn't
# already install its own `_FakeTTLRedis` (most do, for the cross-worker
# pub/sub behavior they're actually testing) would need a live, reachable
# Redis just to get past websocket.accept(). See
# conftest.py::agent_redis_default's docstring. Tests that install their
# own fake via `monkeypatch.setattr("app.core.redis.get_redis", ...)`
# simply override this default for their own duration, same as before.
pytestmark = pytest.mark.usefixtures("agent_redis_default")


def test_link_delivers_capabilities_set_published_by_another_worker(
    db_session, ws_client, monkeypatch
):
    """Task 9 end-to-end proof. `agent_registry.publish_agent_control_frame`
    is exactly what `PUT /agents/{id}/capabilities` (agents.py's
    `put_capabilities`) calls after committing a grant change — calling it
    directly here stands in for that REST request landing on a *different*
    worker process than the one holding this agent's live /link socket (the
    two would share one real Redis instance; `_FakeTTLRedis` plays that role
    for both sides here). What's under test is link_stream's own claim-and-
    deliver wiring, not the registry primitives themselves — those already
    have dedicated coverage in test_agent_registry_connection.py without any
    real /link connection involved at all."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before publishing — otherwise the publish could
        # race ahead of the subscribe and never be delivered at all (ordinary
        # Redis pub/sub fire-and-forget semantics), mirroring
        # test_agent_registry_connection.py's identical precaution.
        time.sleep(0.1)

        published = ws_client.portal.call(
            agent_registry.publish_agent_control_frame,
            agent.id,
            {"type": "capabilities.set", "payload": {"remote_probe": True}},
        )
        assert published is True

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "capabilities.set"
        assert frame["payload"] == {"remote_probe": True}


def test_link_delivers_disconnect_published_by_another_worker(db_session, ws_client, monkeypatch):
    """Companion to the capabilities.set proof above, for `disconnect`. No
    REST/service-layer call site publishes this frame type yet — wiring
    revoke/reject to it is Task 10's job — but link_stream's claim-and-
    deliver path is generic over frame type (`_control_frame_bytes` doesn't
    special-case capabilities.set vs. anything else), so delivery already
    works correctly ahead of Task 10 adding the trigger."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)

        published = ws_client.portal.call(
            agent_registry.publish_agent_control_frame,
            agent.id,
            {"type": "disconnect", "payload": {"reason": "revoked"}},
        )
        assert published is True

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "disconnect"
        assert frame["payload"] == {"reason": "revoked"}


def test_revoke_delivers_immediate_disconnect_over_live_link(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Task 10 end-to-end proof, genuinely exercising the real `POST
    /agents/{id}/revoke` REST endpoint (not `publish_agent_control_frame`
    called directly, unlike the companion proof above which stands in for a
    cross-worker publish) — the trigger this task adds on top of Task 9's
    already-proven generic claim-and-deliver delivery mechanics. Asserts both
    halves of the required behavior: the DB status flip AND the immediate
    disconnect frame landing on the live socket, without waiting for the
    poll-based fallback."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    headers = _login_admin(ws_client, factories)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before the REST call publishes — mirrors the
        # same precaution in the companion cross-worker-publish proof above.
        time.sleep(0.1)

        resp = ws_client.post(
            f"/api/v1/agents/{agent.id}/revoke",
            json={"reason": "compromised"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "disconnect"
        assert frame["payload"] == {"reason": "compromised"}

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.status == "revoked"
    assert refreshed.revoke_reason == "compromised"


def test_reject_publishes_disconnect_control_frame(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Reject's counterpart to the revoke proof above. A rejected agent is
    never expected to hold a live /link socket in normal operation (only a
    still-pending device can be rejected, and pending devices never reach
    /link — see enroll_stream's active/pending/revoked/rejected branching),
    so this asserts the publish call itself lands on the agent's control
    channel — the same level of proof Task 9's own registry-only tests use
    in test_agent_registry_connection.py — rather than a live socket
    delivery, which would require contradicting that invariant."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent
    from app.db.session import SessionLocal

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, _agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.status = "pending"
        db.commit()

    headers = _login_admin(ws_client, factories)

    # Subscribe to the agent's control channel first (mirrors
    # claim_agent_control_frames' own subscribe-then-publish ordering
    # requirement) so the reject endpoint's publish is observed directly,
    # without a live /link connection in the loop.
    pubsub = fake_redis.pubsub()
    ws_client.portal.call(pubsub.subscribe, f"cb:agents:control:{agent.id}")

    resp = ws_client.post(f"/api/v1/agents/{agent.id}/reject", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    msg = ws_client.portal.call(pubsub.get_message, True, 2.0)
    assert msg is not None and msg["type"] == "message"
    frame = json.loads(msg["data"])
    assert frame == {"type": "disconnect", "payload": {"reason": "rejected"}}

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.status == "rejected"


def test_capabilities_put_delivers_immediate_push_over_live_link(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Task 11's first half, end-to-end: the real `PUT
    /agents/{id}/capabilities` REST endpoint (not
    `publish_agent_control_frame` called directly, unlike the companion Task
    9 proof `test_link_delivers_capabilities_set_published_by_another_worker`
    above) delivers a `capabilities.set` push to a live /link socket
    immediately — without waiting for the poll-based fallback or a
    reconnect. Mirrors `test_revoke_delivers_immediate_disconnect_over_live_link`'s
    shape for the capabilities-grant trigger instead of revoke/reject."""
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    headers = _login_admin(ws_client, factories)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before the REST call publishes — mirrors the
        # same precaution in the companion cross-worker-publish proof above.
        time.sleep(0.1)

        resp = ws_client.put(
            f"/api/v1/agents/{agent.id}/capabilities",
            json={"capabilities": {"remote_probe": True}},
            headers=headers,
        )
        assert resp.status_code == 200

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "capabilities.set"
        # The full, authoritative grant set (host_telemetry from
        # _active_agent_with_key's seed data plus the newly-granted
        # remote_probe) — not just the one capability this request named.
        assert frame["payload"] == {"host_telemetry": True, "remote_probe": True}


def test_link_hello_ack_resends_complete_grants_regardless_of_prior_push_success(
    db_session, ws_client
):
    """Task 11's durable-delivery half: the DB stays authoritative, so a
    fresh `hello.ack` on reconnect always carries the *complete* current
    grant set — even when the grant change that produced it was never pushed
    to any live socket at all (the strongest form of "a missed push",
    stronger than a failed `publish_agent_control_frame` call, which Task 9
    already proves never fails the request — see
    test_agents_api.py::test_capabilities_put_succeeds_even_when_control_frame_publish_fails).
    No connection was live when the grant changed here, so there was no
    push to miss; the next hello.ack must still reflect it correctly."""
    from app.db.session import SessionLocal
    from app.services import agent_registry

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        first_ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert first_ack["payload"]["capabilities"] == {"host_telemetry": True}

    # Change the grant set with no /link socket connected at all — nothing
    # to push to, and nothing that could have "failed" to push either.
    with SessionLocal() as db:
        agent_registry.set_capability_grants(
            db, agent.id, {"host_telemetry": False, "remote_probe": True}, actor_user_id=None
        )
        db.commit()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        second_ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert second_ack["type"] == "hello.ack"
        assert second_ack["payload"]["capabilities"] == {
            "host_telemetry": False,
            "remote_probe": True,
        }
