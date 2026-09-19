"""Task 16 / D-12: the agent's reported outbound-spool backlog, persisted from
both heartbeat frames and the initial hello -- explicit zeros clearing a
drained spool, an old/malformed payload surviving without tearing down the
link, and presence (not truthiness) gating every write.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import time

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
    _send_frame,
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


def test_heartbeat_persists_spool_state_on_the_agent_row(db_session, ws_client):
    """A heartbeat carrying `{spool_depth, spool_bytes}` lands on the Agent
    row, so the Agent Detail catch-up indicator is live over a single
    long-lived connection rather than only refreshing on reconnect."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_frame(initiator, ws, seq=1, payload={"spool_depth": 7, "spool_bytes": 8192})
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth == 7
    assert refreshed.spool_bytes == 8192
    assert refreshed.spool_reported_at is not None


def test_heartbeat_with_a_drained_spool_writes_explicit_zeros(db_session, ws_client):
    """The write that *clears* the indicator. The Go heartbeat carries no
    `omitempty`, so a current agent whose backlog has cleared sends an
    explicit 0 — which must overwrite the earlier non-zero depth."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_frame(initiator, ws, seq=1, payload={"spool_depth": 7, "spool_bytes": 8192})
        _send_frame(initiator, ws, seq=2, payload={"spool_depth": 0, "spool_bytes": 0})
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth == 0
    assert refreshed.spool_bytes == 0


def test_old_agent_heartbeat_with_empty_payload_still_accepted(db_session, ws_client):
    """Additive-only: an agent predating HeartbeatPayload sends `{}`. The
    connection must survive it (a later frame still gets through) and the
    three columns must stay NULL — "never reported", not a fabricated 0."""
    from app.db.models import Agent, AgentEvent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_frame(initiator, ws, seq=1, payload={})
        _send_frame(initiator, ws, seq=2, type="log", payload={"msg": "still connected"})
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth is None
    assert refreshed.spool_bytes is None
    assert refreshed.spool_reported_at is None
    assert (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .count()
        == 0
    )


def test_malformed_heartbeat_payload_does_not_tear_down_the_link(db_session, ws_client):
    """A heartbeat whose spool fields are the wrong type is logged and
    ignored — the same posture ws_agents.py takes for a malformed hello.
    The connection stays up and the columns stay NULL."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_frame(initiator, ws, seq=1, payload={"spool_depth": "lots"})
        time.sleep(0.3)

        # Asserted BEFORE the good frame lands: checking only the final state
        # would pass even if the malformed frame had written something that the
        # valid one then overwrote, which is the half of the docstring that
        # actually needs pinning.
        db_session.expire_all()
        mid = db_session.get(Agent, agent.id)
        assert mid.spool_depth is None
        assert mid.spool_bytes is None
        assert mid.spool_reported_at is None

        _send_frame(initiator, ws, seq=2, payload={"spool_depth": 4, "spool_bytes": 512})
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth == 4
    assert refreshed.spool_bytes == 512


def test_heartbeat_without_spool_bytes_leaves_the_byte_column_alone(db_session, ws_client):
    """`spool_bytes` is gated on presence, not just on `spool_depth`.

    NULL means "never reported" and 0 means "reported, empty" — so a payload
    that carries only the depth must leave the byte column at whatever it was,
    not overwrite it with a fabricated 0. Unreachable from a current agent
    (`HeartbeatPayload` carries no `omitempty`, so both keys always ship), but
    the column semantics have to hold for any sender.
    """
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_frame(initiator, ws, seq=1, payload={"spool_depth": 9, "spool_bytes": 4096})
        time.sleep(0.3)
        _send_frame(initiator, ws, seq=2, payload={"spool_depth": 7})
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth == 7
    assert refreshed.spool_bytes == 4096


def test_hello_persists_spool_depth(db_session, ws_client):
    """The at-connect snapshot. `HelloPayload.spool_depth` has been parsed
    since Slice 1 and persisted nowhere; this is the write that closes that
    gap. `hello` carries no byte count, so `spool_bytes` stays NULL until the
    first heartbeat."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"spool_depth": 3})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth == 3
    assert refreshed.spool_bytes is None
    assert refreshed.spool_reported_at is not None


def test_hello_omitting_spool_depth_leaves_the_columns_untouched(db_session, ws_client):
    """Presence, not truthiness — the rule `update_hello_metadata` already
    documents for every other field it copies."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"os": "linux"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.spool_depth is None
    assert refreshed.spool_reported_at is None
