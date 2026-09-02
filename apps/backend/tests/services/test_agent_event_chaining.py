"""Slice 4.3 (F17): agent authorization decisions are tamper-evident.

`record_event` wrote an AgentEvent row and nothing else, so approving,
revoking, re-keying or pushing code to an agent left no hash-chained record
at all.
"""

import pytest

from app.core import audit_chain
from app.db.models import AgentEvent, Log
from app.services import agent_registry


def test_an_authorization_event_writes_a_chained_log(db_session, factories, admin_user):
    agent = factories.agent()

    agent_registry.record_event(db_session, agent.id, "approved", actor_user_id=admin_user.id)
    db_session.commit()

    entry = db_session.query(Log).filter(Log.action == "agent_approved").one()
    assert entry.entity_type == "agent"
    assert entry.entity_id == agent.id
    assert entry.actor_id == admin_user.id
    assert entry.log_hash, "a chained entry must carry its hash"


def test_the_timeline_row_is_still_written(db_session, factories):
    """The agent timeline UI reads agent_events. Chaining is an *additional*
    write, never a replacement."""
    agent = factories.agent()

    agent_registry.record_event(db_session, agent.id, "revoked", detail={"reason": "test"})
    db_session.commit()

    assert db_session.query(AgentEvent).filter(AgentEvent.agent_id == agent.id).count() == 1


def test_a_high_volume_event_is_not_chained(db_session, factories):
    """`connected` fires on every reconnect. audit_chain.lock_audit_chain
    takes a global advisory lock per write, so chaining it would serialize
    every audit write in the instance behind agent churn."""
    agent = factories.agent()

    agent_registry.record_event(db_session, agent.id, "connected")
    db_session.commit()

    assert db_session.query(Log).filter(Log.action == "agent_connected").count() == 0


def test_the_chain_stays_verifiable_across_agent_events(db_session, factories, admin_user):
    agent = factories.agent()
    for event in ("enrolled", "approved", "capability_changed", "revoked"):
        agent_registry.record_event(db_session, agent.id, event, actor_user_id=admin_user.id)
    db_session.commit()

    result = audit_chain.verify_audit_chain(db_session)
    assert result["valid"] is True, result


def test_grant_detail_is_sanitised_into_the_chain(db_session, factories, admin_user):
    """write_log sanitises diff before persisting. Capability details carry
    configuration, so this is the path that keeps a credential out of the
    audit log if one ever appears in a grant."""
    agent = factories.agent()

    agent_registry.record_event(
        db_session,
        agent.id,
        "capability_changed",
        actor_user_id=admin_user.id,
        detail={"host_telemetry": {"enabled": True, "password": "hunter2"}},
    )
    db_session.commit()

    entry = db_session.query(Log).filter(Log.action == "agent_capability_changed").one()
    assert "hunter2" not in (entry.diff or "")


@pytest.mark.parametrize("event_type", sorted(agent_registry.CHAINED_EVENT_TYPES))
def test_every_declared_authorization_event_chains(db_session, factories, event_type):
    agent = factories.agent()

    agent_registry.record_event(db_session, agent.id, event_type)
    db_session.commit()

    assert db_session.query(Log).filter(Log.action == f"agent_{event_type}").count() == 1
