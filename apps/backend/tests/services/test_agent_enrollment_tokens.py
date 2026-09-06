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


# ── Minting ──────────────────────────────────────────────────────────────────


def test_minting_returns_the_plaintext_once_and_stores_only_its_hash(db_session, factories):
    """The row must not be able to reproduce the credential it authorises."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    plaintext, row = tokens.mint_token(
        db_session,
        label="warehouse",
        endpoint_url="https://cb.example.com",
        capabilities={"host_telemetry": True},
        ttl_seconds=3600,
        max_uses=1,
        created_by_user_id=user.id,
    )
    db_session.commit()

    assert plaintext.startswith("cbe_")
    assert len(plaintext) == len("cbe_") + 43  # 32 bytes base64url, unpadded
    assert row.token_hash == tokens.hash_token(plaintext)
    # Nothing on the row, in any column, is the plaintext.
    stored = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    assert plaintext not in repr(stored)


def test_two_mints_never_produce_the_same_token(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    minted = set()
    for i in range(5):
        plaintext, _ = tokens.mint_token(
            db_session,
            label=f"t{i}",
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=3600,
            max_uses=1,
            created_by_user_id=user.id,
        )
        minted.add(plaintext)
    db_session.commit()

    assert len(minted) == 5


@pytest.mark.parametrize(
    "ttl_seconds,max_uses",
    [(0, 1), (-1, 1), (86401, 1), (3600, 0), (3600, -1)],
)
def test_a_token_outside_its_declared_bounds_is_refused(
    db_session, factories, ttl_seconds, max_uses
):
    """TTL and max_uses are what bound a token's blast radius (design §5), so
    both are validated at the only place a token can be created."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    with pytest.raises(ValueError):
        tokens.mint_token(
            db_session,
            label="bad",
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=ttl_seconds,
            max_uses=max_uses,
            created_by_user_id=user.id,
        )


def test_the_ttl_lands_on_the_row_as_an_expiry(db_session, factories):
    """A TTL nobody enforces is decoration."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    before = utcnow()

    _, row = tokens.mint_token(
        db_session,
        label="ttl",
        endpoint_url="https://cb.example.com",
        capabilities={},
        ttl_seconds=600,
        max_uses=1,
        created_by_user_id=user.id,
    )
    db_session.commit()

    assert before + timedelta(seconds=595) <= row.expires_at <= utcnow() + timedelta(seconds=600)


def test_listing_puts_the_newest_token_first(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    for label in ("first", "second", "third"):
        tokens.mint_token(
            db_session,
            label=label,
            endpoint_url="https://cb.example.com",
            capabilities={},
            ttl_seconds=3600,
            max_uses=1,
            created_by_user_id=user.id,
        )
    db_session.commit()

    assert [t.label for t in tokens.list_tokens(db_session)][0] == "third"


# ── Consumption and revocation ───────────────────────────────────────────────


def _mint(db_session, user, **overrides):
    from app.services import agent_enrollment_tokens as tokens

    kwargs = {
        "label": "t",
        "endpoint_url": "https://cb.example.com",
        "capabilities": {"host_telemetry": True},
        "ttl_seconds": 3600,
        "max_uses": 1,
        "created_by_user_id": user.id,
    }
    kwargs.update(overrides)
    plaintext, row = tokens.mint_token(db_session, **kwargs)
    db_session.commit()
    return plaintext, row


def test_consuming_a_live_token_returns_its_scope_and_spends_one_use(db_session, factories):
    from app.db.models import AgentEnrollmentToken
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user)

    consumed = tokens.consume_token(db_session, plaintext)

    assert consumed is not None
    assert consumed.id == row.id
    assert consumed.endpoint_url == "https://cb.example.com"
    assert consumed.capabilities == {"host_telemetry": True}
    assert consumed.created_by_user_id == user.id
    db_session.expire_all()
    assert db_session.get(AgentEnrollmentToken, row.id).uses == 1


def test_a_multi_use_token_is_spent_exactly_max_uses_times(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, _ = _mint(db_session, user, max_uses=3)

    assert [tokens.consume_token(db_session, plaintext) is not None for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]


@pytest.mark.parametrize("case", ["unknown", "expired", "revoked", "spent"])
def test_every_failure_mode_is_the_same_answer(db_session, factories, case):
    """Not an oracle (design §4): a caller must not be able to tell an unknown
    token from a spent, revoked or expired one — that difference is exactly
    what would let someone probe for live tokens."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()

    if case == "unknown":
        assert tokens.consume_token(db_session, "cbe_nothing-like-this") is None
        return

    plaintext, row = _mint(db_session, user)
    if case == "expired":
        row.expires_at = utcnow() - timedelta(seconds=1)
    elif case == "revoked":
        row.revoked_at = utcnow()
    elif case == "spent":
        row.uses = row.max_uses
    db_session.commit()

    assert tokens.consume_token(db_session, plaintext) is None


def test_a_token_one_second_from_expiry_still_works(db_session, factories):
    """The boundary in the other direction: `expires_at > now()` must not be
    off by a comparison, or every token would die early."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user)
    row.expires_at = utcnow() + timedelta(seconds=30)
    db_session.commit()

    assert tokens.consume_token(db_session, plaintext) is not None


def test_revoking_shuts_a_token_that_still_has_uses_left(db_session, factories):
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    plaintext, row = _mint(db_session, user, max_uses=5)

    revoked = tokens.revoke_token(db_session, row.id)
    db_session.commit()

    assert revoked is not None and revoked.revoked_at is not None
    assert tokens.consume_token(db_session, plaintext) is None


def test_revoking_twice_keeps_the_first_timestamp(db_session, factories):
    """The first revocation is the honest one, and a second click is not an
    error the operator should be shown."""
    from app.services import agent_enrollment_tokens as tokens

    user = factories.user(role="admin")
    db_session.commit()
    _, row = _mint(db_session, user)

    first = tokens.revoke_token(db_session, row.id).revoked_at
    db_session.commit()
    second = tokens.revoke_token(db_session, row.id).revoked_at

    assert first == second


def test_revoking_an_unknown_token_is_none_not_an_error(db_session):
    from app.services import agent_enrollment_tokens as tokens

    assert tokens.revoke_token(db_session, 999_999) is None
