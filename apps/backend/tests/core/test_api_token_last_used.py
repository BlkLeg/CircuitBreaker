"""`touch_api_token_last_used` writes, throttles, and never blocks auth.

The function deliberately writes on its own connection, so a row created inside
the `db_session` fixture's uncommitted SAVEPOINT is invisible to it. These tests
therefore commit their rows on a real connection, which is also the only way to
prove the stamp actually lands rather than silently no-opping.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from app.core.constants import API_TOKEN_LAST_USED_TOUCH_SECONDS
from app.core.security import (
    create_salted_api_token_hash,
    touch_api_token_last_used,
)
from app.core.time import utcnow, utcnow_iso
from app.db import session as _db_session
from app.db.models import APIToken, User


def _committed_token(**kwargs: object) -> int:
    """Create an APIToken on its own connection and return its id."""
    with _db_session.SessionLocal() as writer:
        owner = writer.query(User).order_by(User.id).first()
        if owner is None:
            owner = User(
                email=f"last-used-owner-{secrets.token_hex(4)}@test.invalid",
                hashed_password="!",
                role="admin",
                is_admin=True,
                is_superuser=False,
                is_active=False,
                display_name="last used owner",
                provider="local",
                created_at=utcnow_iso(),
            )
            writer.add(owner)
            writer.flush()
        row = APIToken(
            token_hash=create_salted_api_token_hash(secrets.token_urlsafe(16)),
            label=f"last-used-{secrets.token_hex(4)}",
            created_by=owner.id,
            scopes=["read:*"],
            **kwargs,
        )
        writer.add(row)
        writer.commit()
        return int(row.id)


def _last_used(token_id: int):  # type: ignore[no-untyped-def]
    with _db_session.SessionLocal() as reader:
        row = reader.get(APIToken, token_id)
        return None if row is None else row.last_used_at


def _delete(token_id: int) -> None:
    with _db_session.SessionLocal() as cleaner:
        row = cleaner.get(APIToken, token_id)
        if row is not None:
            cleaner.delete(row)
            cleaner.commit()


def test_stamps_a_token_that_has_never_been_used(setup_db) -> None:
    token_id = _committed_token()
    try:
        with _db_session.SessionLocal() as reader:
            row = reader.get(APIToken, token_id)
            assert row is not None
            assert row.last_used_at is None
            touch_api_token_last_used(row)

        assert _last_used(token_id) is not None
    finally:
        _delete(token_id)


def test_throttles_a_recent_stamp(setup_db) -> None:
    recent = utcnow() - timedelta(seconds=API_TOKEN_LAST_USED_TOUCH_SECONDS // 2)
    token_id = _committed_token(last_used_at=recent)
    try:
        with _db_session.SessionLocal() as reader:
            row = reader.get(APIToken, token_id)
            assert row is not None
            touch_api_token_last_used(row)

        # Unchanged: the throttle window has not elapsed.
        assert _last_used(token_id) == recent
    finally:
        _delete(token_id)


def test_restamps_once_the_throttle_window_has_passed(setup_db) -> None:
    stale = utcnow() - timedelta(seconds=API_TOKEN_LAST_USED_TOUCH_SECONDS * 2)
    token_id = _committed_token(last_used_at=stale)
    try:
        with _db_session.SessionLocal() as reader:
            row = reader.get(APIToken, token_id)
            assert row is not None
            touch_api_token_last_used(row)

        refreshed = _last_used(token_id)
        assert refreshed is not None and refreshed > stale
    finally:
        _delete(token_id)


def test_gives_up_rather_than_waiting_on_a_locked_row(setup_db) -> None:
    """The regression this function was rewritten for.

    A held row lock used to stall authentication for as long as the other
    transaction lived. The stamp must now return promptly and leave the row
    alone instead.
    """
    stale = utcnow() - timedelta(seconds=API_TOKEN_LAST_USED_TOUCH_SECONDS * 2)
    token_id = _committed_token(last_used_at=stale)
    try:
        holder = _db_session.SessionLocal()
        try:
            # Take and keep a write lock on the row, the way a long-running
            # transaction elsewhere in the app would.
            holder.execute(
                APIToken.__table__.select().where(APIToken.id == token_id).with_for_update()
            )

            started = utcnow()
            with _db_session.SessionLocal() as reader:
                row = reader.get(APIToken, token_id)
                assert row is not None
                touch_api_token_last_used(row)
            elapsed = (utcnow() - started).total_seconds()

            # Bounded by lock_timeout, not by the holder's lifetime.
            assert elapsed < 5
        finally:
            holder.rollback()
            holder.close()

        # The contended write was skipped, not applied.
        assert _last_used(token_id) == stale
    finally:
        _delete(token_id)


def test_ignores_a_row_without_an_id() -> None:
    class Detached:
        id = None
        last_used_at = None

    touch_api_token_last_used(Detached())
