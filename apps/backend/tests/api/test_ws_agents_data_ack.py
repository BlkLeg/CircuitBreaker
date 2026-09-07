"""The server half of acknowledged delivery (plan Phase 5).

Every test here drives a real /link WebSocket — real Noise handshake, real
encrypted frames — because the property under test is not "does the ack
function work" but "does this connection ever tell an agent to discard an
observation it should have kept". That is a wiring question, and only the
wiring can answer it.
"""

import contextlib
import json
from datetime import UTC, datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from app.services import agent_link
from tests.api.test_ws_agents_link import _active_agent_with_key, _send_hello
from tests.helpers.agent_noise_client import TestNoiseInitiator

pytestmark = pytest.mark.usefixtures("agent_redis_default")

# Long enough that nothing in these tests races it, short enough that a test
# waiting for the server's next unprompted frame finishes in a second or two.
# Every test that has to prove a *negative* ("no ack was sent") reads frames
# until this ping arrives, because a ping is the one frame the server is
# guaranteed to send on its own schedule.
_FAST_PING_SECONDS = 0.6


@pytest.fixture(autouse=True)
def _fast_ping(monkeypatch):
    monkeypatch.setattr("app.api.ws_agents._LINK_PING_INTERVAL_SECONDS", _FAST_PING_SECONDS)


def _connect(ws, agent_priv, server_pub, *, ack_data: bool):
    """Handshake, hello (asking for acks or not), and drain the connect frames.

    Returns the initiator and the decoded hello.ack payload, so a caller can
    assert what the negotiation actually settled.
    """
    initiator = TestNoiseInitiator(agent_priv, server_pub)
    ws.send_bytes(initiator.write_message())
    initiator.read_message(ws.receive_bytes())
    _send_hello(initiator, ws, payload={"ack_data": True} if ack_data else {})
    ack = json.loads(initiator.decrypt(ws.receive_bytes()))
    assert ack["type"] == "hello.ack"
    assert ack["payload"]["accepted"] is True
    assert json.loads(initiator.decrypt(ws.receive_bytes()))["type"] == "capabilities.set"
    return initiator, ack["payload"]


def _send_frame(initiator, ws, *, seq, frame_type="heartbeat", v=1, payload=None):
    frame = {
        "v": v,
        "type": frame_type,
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload if payload is not None else {},
    }
    ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))


def _read_until_ping(initiator, ws, *, limit=40):
    """Every server frame up to and including the next `ping`.

    A ping is the server's own unprompted heartbeat request, so it is a
    reliable "nothing further is coming right now" marker — which is what a
    test asserting that *no* acknowledgement was sent needs.
    """
    frames = []
    for _ in range(limit):
        frame = json.loads(initiator.decrypt(ws.receive_bytes()))
        frames.append(frame)
        if frame["type"] == "ping":
            return frames
    raise AssertionError(f"no ping within {limit} frames: {[f['type'] for f in frames]}")


def _acks(frames):
    return [f for f in frames if f["type"] == "data.ack"]


def test_link_grants_acknowledged_delivery_only_to_an_agent_that_asked(db_session, ws_client):
    """Both halves of the negotiation, on the wire.

    The flag is what makes this change safe to deploy against a mixed fleet:
    an agent that never asked must not be sent a frame type its build has
    never heard of, and an agent that did ask must be told plainly that it may
    switch to commit-on-ack. Guessing either way is what a flag day looks
    like.
    """
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _, payload = _connect(ws, agent_priv, server_pub, ack_data=True)
        assert payload["data_ack"] is True

    agent, agent_priv = _active_agent_with_key(db_session)
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _, payload = _connect(ws, agent_priv, server_pub, ack_data=False)
        assert payload["data_ack"] is False


def test_link_records_the_negotiated_delivery_mode_on_the_agent_row(db_session, ws_client):
    """`agents.data_ack_negotiated`, which is how an operator sees which of a
    mixed fleet is still at-most-once.

    NULL before either agent connects, and it must become an explicit False —
    not stay NULL — for an agent that did not ask: "this build cannot confirm
    delivery" is a fact worth showing, and it is a different fact from "this
    agent has not connected since the server learned to report it".
    """
    from app.db.models import Agent

    asking, asking_priv = _active_agent_with_key(db_session)
    silent, silent_priv = _active_agent_with_key(db_session)
    assert asking.data_ack_negotiated is None
    assert silent.data_ack_negotiated is None
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect(ws, asking_priv, server_pub, ack_data=True)
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect(ws, silent_priv, server_pub, ack_data=False)

    db_session.expire_all()
    assert db_session.get(Agent, asking.id).data_ack_negotiated is True
    assert db_session.get(Agent, silent.id).data_ack_negotiated is False


def test_link_never_acks_an_agent_that_did_not_negotiate(db_session, ws_client):
    """Old agent, new server. It must see exactly the protocol it knows.

    The agent's inbound switch has no `default:` arm, so an unknown frame type
    is ignored rather than fatal — but "it would probably be harmless" is not
    the guarantee. The server simply does not send them.
    """
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, payload = _connect(ws, agent_priv, server_pub, ack_data=False)
        assert payload["data_ack"] is False
        for seq in range(1, 7):
            _send_frame(initiator, ws, seq=seq)
        frames = _read_until_ping(initiator, ws)

    assert _acks(frames) == [], [f["type"] for f in frames]


def test_link_watermark_advances_once_the_frame_is_persisted(db_session, ws_client):
    """The watermark advances after `dispatch_frame` returns — which is after
    it has committed — and coalesces four frames into one ack.

    Coalescing is free here in a way it would not be for a per-frame receipt:
    the ack is a watermark, so one frame saying "everything through 4" is the
    same statement as four frames saying "1", "2", "3", "4".
    """
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
        for seq in range(1, 5):
            _send_frame(initiator, ws, seq=seq)
        frames = _read_until_ping(initiator, ws)

    acks = _acks(frames)
    assert acks, [f["type"] for f in frames]
    assert acks[-1]["payload"]["seq"] == 4
    # One ack for the batch, not one per frame — the coalescing threshold.
    assert len(acks) == 1, [a["payload"] for a in acks]


def test_link_acks_a_lone_frame_without_waiting_for_a_full_batch(db_session, ws_client):
    """The time half of the coalescing rule.

    A single sample arriving on an otherwise quiet link must not sit
    unacknowledged waiting for three more that may be a cadence-interval away
    — the agent is holding it, and everything behind it, until this arrives.
    """
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
        _send_frame(initiator, ws, seq=1)
        frames = _read_until_ping(initiator, ws)

    acks = _acks(frames)
    assert acks, [f["type"] for f in frames]
    assert acks[0]["payload"]["seq"] == 1


def test_link_watermark_advances_past_a_frame_it_refuses(db_session, ws_client):
    """The single most important correctness point in the whole mechanism.

    A frame the server decoded and then terminally refused — an unsupported
    protocol version here, and equally a duplicate or decreasing sequence — is
    never going to be accepted, however many times it is re-sent. If the
    watermark only moved on success, that frame would sit at the head of the
    agent's spool forever, be re-sent on every connection, and hold up
    everything queued behind it until the spool's cap destroyed it all. The
    durability fix would have become a data-loss bug.
    """
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
        for seq in range(1, 4):
            _send_frame(initiator, ws, seq=seq)
        # Decodable, and refused for good: `v` is not this server's protocol
        # version. The sequence number is still trustworthy, which is exactly
        # what makes it safe to acknowledge.
        _send_frame(initiator, ws, seq=9, v=2)
        frames = _read_until_ping(initiator, ws)

    acks = _acks(frames)
    assert acks, [f["type"] for f in frames]
    assert acks[-1]["payload"]["seq"] == 9, (
        "the watermark stopped at the refused frame — the agent's spool would wedge behind it"
    )


def test_link_watermark_advances_past_a_duplicate_sequence(db_session, ws_client):
    """The replay case, which is the one an at-least-once agent actually
    produces: everything uncommitted when a socket dies is re-sent on the next
    connection, and the server's sequence guard refuses the repeat. Refusing
    it and then never acknowledging it would strand the agent."""
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
        _send_frame(initiator, ws, seq=1)
        _send_frame(initiator, ws, seq=2)
        _send_frame(initiator, ws, seq=2)  # duplicate — refused, and terminal
        _send_frame(initiator, ws, seq=3)
        frames = _read_until_ping(initiator, ws)

    acks = _acks(frames)
    assert acks, [f["type"] for f in frames]
    assert acks[-1]["payload"]["seq"] == 3


def test_link_freezes_acknowledgement_after_a_malformed_frame(db_session, ws_client, caplog):
    """A frame whose envelope did not parse has no sequence number worth
    acknowledging, so the server stops acknowledging anything for the rest of
    the connection rather than acknowledging past a hole it cannot see.

    The agent then commits nothing more and re-sends everything on reconnect.
    That is deliberately harsh: the alternative is telling an agent to discard
    observations on the strength of a claim this server can no longer make.
    """
    import logging

    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with caplog.at_level(logging.WARNING, logger="app.api.ws_agents"):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
            for seq in range(1, 5):
                _send_frame(initiator, ws, seq=seq)
            before = _read_until_ping(initiator, ws)
            assert _acks(before), "the fixture never reached a working ack"

            # Decrypts cleanly, then fails to parse as a frame at all — the
            # `malformed_frame` rejection, distinct from an undecryptable one.
            ws.send_bytes(initiator.encrypt(b"not json at all"))
            for seq in range(5, 12):
                _send_frame(initiator, ws, seq=seq)
            after = _read_until_ping(initiator, ws)

    assert _acks(after) == [], [f["type"] for f in after]
    assert any("froze delivery acknowledgement" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_link_freezes_acknowledgement_after_an_undecryptable_frame(db_session, ws_client, caplog):
    """Same freeze, one layer lower.

    An undecryptable frame means the two ciphers have desynced, so this
    connection's view of what the agent sent is no longer trustworthy and the
    link is doomed regardless. It stays non-fatal — an adversarial peer must
    not be able to kill a link with one bad frame — but it must stop this
    server making delivery claims it cannot support.
    """
    import logging

    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with caplog.at_level(logging.WARNING, logger="app.api.ws_agents"):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
            # Establish a working ack first. Without this the test would pass
            # just as happily if the bad ciphertext desynced the responder so
            # that nothing after it decrypted at all — "no acks arrived" would
            # then be true for entirely the wrong reason, and the freeze it
            # claims to cover would be untested.
            for seq in range(1, 5):
                _send_frame(initiator, ws, seq=seq)
            before = _read_until_ping(initiator, ws)
            assert _acks(before), "the fixture never reached a working ack"

            ws.send_bytes(b"not-a-valid-noise-ciphertext")
            for seq in range(5, 12):
                _send_frame(initiator, ws, seq=seq)
            frames = _read_until_ping(initiator, ws)

    assert _acks(frames) == [], [f["type"] for f in frames]
    assert any("froze delivery acknowledgement" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_link_acks_a_frame_the_capability_gate_destroyed(db_session, ws_client):
    """The refusal path that actually happens in the field, end to end.

    `dispatch_frame` drops a `telemetry.host` sample outright when the
    agent's `host_telemetry` grant is off — the sample is destroyed here, not
    queued, and counted on the agent's row. It is as terminal as an ingest,
    and the watermark has to say so.

    If it did not, the frame would sit at the head of the agent's spool for
    the life of the agent: re-sent on every connection, refused every time,
    holding up every observation queued behind it until the spool's size cap
    destroyed the lot. Turning a durability fix into a data-loss bug is
    exactly what this assertion exists to prevent.
    """
    from app.db.models import Agent, AgentCapabilityGrant
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as setup_db:
        grant = (
            setup_db.query(AgentCapabilityGrant)
            .filter_by(agent_id=agent.id, capability="host_telemetry")
            .one()
        )
        grant.enabled = False
        setup_db.commit()
    _, server_pub = get_server_static_keypair()

    sample = {
        "schema": 1,
        "sample_id": "a" * 32,
        "status": "ok",
        "summary": {"cpu_pct": 1.0},
    }
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
        for seq in range(1, 5):
            _send_frame(initiator, ws, seq=seq, frame_type="telemetry.host", payload=sample)
        frames = _read_until_ping(initiator, ws)

    acks = _acks(frames)
    assert acks, [f["type"] for f in frames]
    assert acks[-1]["payload"]["seq"] == 4

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.refused_frames == 4, (
        "the fixture did not actually exercise the capability gate's refusal path"
    )


def test_link_never_acks_a_frame_whose_handler_raised(db_session, ws_client, monkeypatch):
    """No acknowledgement may ever name a frame this server did not store.

    `note_handled` sits after `await dispatch_frame` because that call commits:
    at that point the frame is durably persisted (or deliberately refused and
    counted), which is what makes the acknowledgement a statement about the
    database rather than about having read a socket.

    Being honest about what this can and cannot catch: moving `note_handled`
    one line up is, on today's loop, unobservable — nothing flushes between the
    two statements, and an exception escaping `dispatch_frame` tears the
    connection down before the next flush can run, so the watermark dies
    unsent either way. The regression that *is* reachable is the plausible
    one: a future change that decides a handler blowing up should not kill the
    link, swallows the exception and carries on. Combined with a premature
    `note_handled` that immediately starts acknowledging observations this
    server threw away.

    So both halves are asserted — the frame is never acknowledged, and the
    connection does drop — and the second assertion's message says what has to
    be re-established if that ever changes.
    """
    real_dispatch = agent_link.dispatch_frame

    async def exploding_dispatch(db, agent, frame):
        if frame.seq >= 5:
            raise RuntimeError("handler blew up while storing the sample")
        await real_dispatch(db, agent, frame)

    monkeypatch.setattr("app.services.agent_link.dispatch_frame", exploding_dispatch)

    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    frames: list[dict] = []
    dropped = False
    try:
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator, _ = _connect(ws, agent_priv, server_pub, ack_data=True)
            for seq in range(1, 5):
                _send_frame(initiator, ws, seq=seq)
            frames.extend(_read_until_ping(initiator, ws))
            assert [a["payload"]["seq"] for a in _acks(frames)] == [4], (
                "the fixture never reached a working ack, so it cannot show one being withheld"
            )

            # Now the one whose handler raises — and a few behind it, so a
            # server that swallowed the failure and carried on would have
            # every reason to emit another ack.
            for seq in range(5, 10):
                _send_frame(initiator, ws, seq=seq)
            # Read until the socket dies (the expected outcome) or two more
            # pings have gone by — long enough that a server which swallowed
            # the failure and carried on would have flushed an ack by now,
            # short enough that this does not sit on the suite's timeout.
            pings = 0
            with contextlib.suppress(WebSocketDisconnect, RuntimeError, ValueError, OSError):
                while pings < 2:
                    frame = json.loads(initiator.decrypt(ws.receive_bytes()))
                    frames.append(frame)
                    if frame["type"] == "ping":
                        pings += 1
    except RuntimeError as exc:  # re-raised by the test client on teardown
        if "handler blew up" not in str(exc):
            raise
        dropped = True

    acked = [a["payload"]["seq"] for a in _acks(frames)]
    assert 5 not in acked and max(acked) == 4, (
        f"a frame whose handler raised was acknowledged — acks = {acked}. The agent would have "
        f"discarded an observation this server never stored."
    )
    assert dropped, (
        "the connection survived a handler that raised. That may be a deliberate change, but the "
        "watermark's honesty currently rests on it: nothing else stops a frame being acknowledged "
        "between `note_handled` and a commit that never happened."
    )
