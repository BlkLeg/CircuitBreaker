"""Slice B: the enrollment-token table and the service over it.

Design: `docs/design/2026-09-05-agent-reachability-design.md` §3.2, §3.3, §4.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.time import utcnow


def test_a_token_row_round_trips_every_column(db_session, factories):
    from app.db.models import AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()

    row = AgentEnrollmentToken(
        token_hash="a" * 64,
        label="warehouse fleet",
        endpoint_url="https://cb.example.com",
        capabilities={"host_telemetry": True},
        max_uses=3,
        uses=0,
        expires_at=utcnow() + timedelta(hours=1),
        created_by_user_id=user.id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(AgentEnrollmentToken, row.id)
    assert stored.token_hash == "a" * 64
    assert stored.capabilities == {"host_telemetry": True}
    assert stored.max_uses == 3
    assert stored.uses == 0
    assert stored.revoked_at is None
    assert stored.created_at is not None


def test_the_token_hash_is_unique(db_session, factories):
    """Two rows for one token would make consumption ambiguous."""
    from sqlalchemy.exc import IntegrityError

    from app.db.models import AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()

    def _row() -> AgentEnrollmentToken:
        return AgentEnrollmentToken(
            token_hash="b" * 64,
            label="dup",
            endpoint_url="https://cb.example.com",
            capabilities={},
            max_uses=1,
            expires_at=utcnow() + timedelta(hours=1),
            created_by_user_id=user.id,
        )

    db_session.add(_row())
    db_session.commit()
    db_session.add(_row())
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_an_agent_can_name_the_token_it_came_from(db_session, factories):
    """Provenance survives revocation: tokens are revoked, never deleted."""
    from app.db.models import Agent, AgentEnrollmentToken

    user = factories.user(role="admin")
    db_session.commit()
    token = AgentEnrollmentToken(
        token_hash="c" * 64,
        label="provenance",
        endpoint_url="https://cb.example.com",
        capabilities={},
        max_uses=1,
        expires_at=utcnow() + timedelta(hours=1),
        created_by_user_id=user.id,
    )
    db_session.add(token)
    db_session.commit()

    agent = factories.agent(status="active")
    agent.enrollment_token_id = token.id
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(Agent, agent.id).enrollment_token_id == token.id
