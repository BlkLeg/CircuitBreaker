"""Slice B: an agent presenting a valid token enrolls with no human present.

Design: `docs/design/2026-09-05-agent-reachability-design.md` §4, §10.

The token has to be **really** committed. `db_session` is SAVEPOINT-isolated and
never commits, so a token minted through it is invisible to the separate
`SessionLocal()` connection `enroll_stream` opens — the handler would find
nothing and every test here would pass for the wrong reason. `minted_token`
commits on its own session; conftest's reaper cleans it up.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from tests.helpers.agent_noise_client import TestNoiseInitiator

# Same reason as test_ws_agents_enroll.py: every /enroll connection runs
# through the Redis-backed attempt-rate gate before any Noise byte is read.
pytestmark = pytest.mark.usefixtures("agent_redis_default")

ENDPOINT_URL = "https://cb.example.com"


def _hello_bytes(**overrides) -> bytes:
    payload = {
        "hostname": "warehouse-01",
        "os": "linux",
        "os_version": "6.1",
        "arch": "amd64",
        "agent_version": "0.1.0",
        "server_url": ENDPOINT_URL,
    }
    payload.update(overrides)
    frame = {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    return json.dumps(frame).encode()


def _enroll(ws_client, **hello_overrides) -> dict:
    """Drive one real /enroll connection and return the ack payload.

    Raises `WebSocketDisconnect` when the server closes without acking, which
    is what every refusal looks like from here — deliberately, since the caller
    must not be able to tell why.
    """
    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        ws.send_bytes(initiator.encrypt(_hello_bytes(**hello_overrides)))
        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
    return ack["payload"]


@pytest.fixture
def minted_token(db_session, request):
    """A token committed on its own connection, so `enroll_stream` can see it.

    Cleanup is `conftest._reap_agents_committed_outside_the_test`, which now
    includes `AgentEnrollmentToken`. Deleting the token here instead would fail:
    fixtures tear down in reverse setup order, so this would run *before* the
    agents that reference it are reaped, and the foreign key would refuse.
    """
    from sqlalchemy.orm import Session

    from app.db.session import engine
    from app.services import agent_enrollment_tokens

    overrides = getattr(request, "param", {})
    with Session(engine) as setup:
        plaintext, row = agent_enrollment_tokens.mint_token(
            setup,
            label="warehouse fleet",
            endpoint_url=ENDPOINT_URL,
            capabilities=overrides.get("capabilities", {"host_telemetry": True}),
            ttl_seconds=overrides.get("ttl_seconds", 3600),
            max_uses=overrides.get("max_uses", 1),
            created_by_user_id=None,
        )
        setup.commit()
        token_id = row.id
    return plaintext, token_id


def test_a_valid_token_enrolls_the_agent_active_with_its_scope(db_session, ws_client, minted_token):
    """The whole feature: no pairing code, no approval screen, and the grants
    the token named written at the moment of enrollment."""
    from app.db.models import Agent, AgentCapabilityGrant

    plaintext, token_id = minted_token

    ack = _enroll(ws_client, enroll_token=plaintext)

    assert ack["status"] == "active"
    assert "pairing_code" not in ack
    assert "magic_link" not in ack

    db_session.expire_all()
    agent = db_session.get(Agent, ack["agent_id"])
    assert agent.status == "active"
    assert agent.approved_at is not None
    assert agent.enrollment_token_id == token_id
    assert agent.enrolled_via_endpoint == ENDPOINT_URL

    grants = (
        db_session.query(AgentCapabilityGrant)
        .filter(AgentCapabilityGrant.agent_id == agent.id)
        .all()
    )
    assert grants, "auto-approval must write grant rows, exactly as approve_agent does"
    assert {g.capability: g.enabled for g in grants}["host_telemetry"] is True


def test_a_spent_token_is_refused_and_creates_nothing(db_session, ws_client, minted_token):
    """And is refused the same way an unknown one is."""
    from app.db.models import Agent

    plaintext, _ = minted_token
    _enroll(ws_client, enroll_token=plaintext)
    db_session.expire_all()
    before = db_session.query(Agent).count()

    with pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token=plaintext)

    db_session.expire_all()
    assert db_session.query(Agent).count() == before


def test_an_unknown_token_is_refused_identically(db_session, ws_client):
    from app.db.models import Agent

    before = db_session.query(Agent).count()

    with pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token="cbe_not-a-real-token-at-all")

    db_session.expire_all()
    assert db_session.query(Agent).count() == before


@pytest.mark.parametrize("minted_token", [{"ttl_seconds": 1}], indirect=True)
def test_an_expired_token_is_refused(db_session, ws_client, minted_token):
    """Expiry is enforced where it matters, not only in the service unit test."""
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from app.core.time import utcnow
    from app.db.models import AgentEnrollmentToken
    from app.db.session import engine

    plaintext, token_id = minted_token
    with Session(engine) as session:
        session.execute(
            update(AgentEnrollmentToken)
            .where(AgentEnrollmentToken.id == token_id)
            .values(expires_at=utcnow())
        )
        session.commit()

    with pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token=plaintext)


def test_a_revoked_token_is_refused(db_session, ws_client, minted_token):
    from sqlalchemy.orm import Session

    from app.db.session import engine
    from app.services import agent_enrollment_tokens

    plaintext, token_id = minted_token
    with Session(engine) as session:
        agent_enrollment_tokens.revoke_token(session, token_id)
        session.commit()

    with pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token=plaintext)


def test_a_hello_with_no_token_still_enrolls_pending(db_session, ws_client):
    """The attended flow is unchanged, and an agent predating this slice sends
    no token at all — a half-updated deployment must still work."""
    from app.db.models import Agent

    ack = _enroll(ws_client)

    assert "pairing_code" in ack
    db_session.expire_all()
    assert db_session.get(Agent, ack["agent_id"]).status == "pending"


def test_a_token_enrollment_is_not_subject_to_the_pending_cap(
    db_session, ws_client, minted_token, monkeypatch
):
    """A token-enrolled agent is never pending, so counting it against that cap
    would deadlock every unattended boot."""
    from app.services import agent_registry

    monkeypatch.setattr(agent_registry, "MAX_CONCURRENT_PENDING_AGENTS", 0)
    plaintext, _ = minted_token

    ack = _enroll(ws_client, enroll_token=plaintext)

    assert ack["status"] == "active"


@pytest.mark.parametrize("minted_token", [{"max_uses": 2}], indirect=True)
def test_a_multi_use_token_enrolls_each_machine_once(db_session, ws_client, minted_token):
    """The case that motivates max_uses: one token in a launch template, N
    instances booting."""
    from app.db.models import Agent

    plaintext, _ = minted_token

    first = _enroll(ws_client, enroll_token=plaintext, hostname="node-a")
    second = _enroll(ws_client, enroll_token=plaintext, hostname="node-b")
    with pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token=plaintext, hostname="node-c")

    assert first["agent_id"] != second["agent_id"]
    db_session.expire_all()
    assert db_session.get(Agent, first["agent_id"]).status == "active"
    assert db_session.get(Agent, second["agent_id"]).status == "active"


def test_the_token_never_reaches_the_logs(ws_client, caplog, minted_token):
    """A credential in a log file outlives its TTL in every backup."""
    import logging

    plaintext, _ = minted_token
    with caplog.at_level(logging.DEBUG):
        _enroll(ws_client, enroll_token=plaintext)

    assert plaintext not in caplog.text


def test_a_refused_token_is_not_named_in_the_logs_either(ws_client, caplog):
    """A rejected token is still a credential someone typed."""
    import logging

    with caplog.at_level(logging.DEBUG), pytest.raises(WebSocketDisconnect):
        _enroll(ws_client, enroll_token="cbe_rejected-but-still-secret")

    assert "cbe_rejected-but-still-secret" not in caplog.text
