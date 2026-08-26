"""Mint a service-account JWT the way the API does — token *and* APIToken row.

A service-account JWT is live only while the `APIToken` row holding its salted hash is
(`core.security.service_account_token_is_live`). Tests that call `create_token(0, ...)`
directly produce a well-signed token that no install ever issued, and it is refused 401
rather than reaching whatever the test meant to assert.

That refusal is correct, so the fix is to give these tokens their row rather than to
weaken the gate. This module is the one place that knows how the two fit together.
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security import create_salted_api_token_hash, create_token
from app.core.time import utcnow_iso
from app.db.models import APIToken, User
from app.services.settings_service import get_or_create_settings

_SERVICE_ACCOUNT_LABEL_PREFIX = "[Service Account] "


def _owner_id(db: Session) -> int:
    """`APIToken.created_by` is a foreign key, so the row needs a user to belong to.

    Reuse whichever user the caller's session already has; create an inert one only when
    there is none, so a test that never asked for a user does not silently acquire a
    usable account. The service account authenticates as the sentinel either way — this
    owner is bookkeeping, not the identity under test.
    """
    owner = db.query(User).order_by(User.id).first()
    if owner is not None:
        return owner.id
    owner = User(
        email=f"service-account-owner-{secrets.token_hex(4)}@test.invalid",
        hashed_password="!",  # unusable: no password hashes to a bare "!"
        role="admin",
        is_admin=True,
        is_superuser=False,
        is_active=False,
        display_name="service account owner",
        provider="local",
        created_at=utcnow_iso(),
    )
    db.add(owner)
    db.flush()
    return owner.id


def _mint(
    db: Session,
    *,
    scopes: list[str],
    label: str,
    hours: int,
    expires_at: datetime | None,
    created_by: int,
) -> tuple[str, APIToken]:
    cfg = get_or_create_settings(db)
    token = create_token(
        0,
        cfg.jwt_secret,
        hours,
        scopes=scopes,
        extra_claims={"label": label, "jti": secrets.token_urlsafe(16)},
    )
    row = APIToken(
        token_hash=create_salted_api_token_hash(token),
        label=f"{_SERVICE_ACCOUNT_LABEL_PREFIX}{label}",
        created_by=created_by,
        scopes=scopes,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return token, row


def mint_service_account_token(
    db: Session,
    *,
    scopes: list[str],
    label: str = "test service account",
    hours: int = 24,
    expires_at: datetime | None = None,
    created_by: int | None = None,
) -> str:
    """Return a service-account JWT that `service_account_token_is_live` accepts.

    For routes served through the `client` fixture, which shares the test's session.
    WebSocket routes open their own — see `service_account_on_its_own_connection`.
    """
    owner = _owner_id(db) if created_by is None else created_by
    token, _ = _mint(
        db, scopes=scopes, label=label, hours=hours, expires_at=expires_at, created_by=owner
    )
    db.commit()
    return token


@contextmanager
def service_account_on_its_own_connection(
    db: Session, *, scopes: list[str], label: str = "test service account", hours: int = 24
):
    """Yield a service-account JWT whose APIToken row other connections can see.

    The `db_session` fixture keeps every write inside a SAVEPOINT on one connection, so
    a row committed through it is invisible to code that opens its own session — and the
    monitor stream does exactly that (`ws_monitors.py` uses `SessionLocal()`). Such a row
    also escapes the fixture's rollback, so this deletes it, along with the owner it had
    to create to satisfy the foreign key.
    """
    from app.db import session as _db_session

    with _db_session.SessionLocal() as writer:
        owner = _owner_id(writer)
        token, row = _mint(
            writer, scopes=scopes, label=label, hours=hours, expires_at=None, created_by=owner
        )
        row_id = row.id
        writer.commit()
    try:
        yield token
    finally:
        with _db_session.SessionLocal() as cleaner:
            row = cleaner.get(APIToken, row_id)
            if row is not None:
                cleaner.delete(row)
            cleaner.commit()
