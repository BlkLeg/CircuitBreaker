"""Short-lived bearer tokens that enroll an agent with no human present.

The attended flow — a human comparing a device fingerprint and pressing approve
— is unchanged and remains the default. This is opt-in, and §5 of
`docs/design/2026-09-05-agent-reachability-design.md` states its cost plainly: a
multi-use token in a launch template is a credential that will enroll anything
presenting it, for its whole TTL. The attended design has the stronger property
that no bearer secret exists at all.

Everything here exists to bound that cost. The plaintext is returned once and
stored only as a SHA-256 hash; a TTL is required and capped; `max_uses`
defaults to 1; a token is scoped to one endpoint and one capability set;
revocation takes effect immediately; and consumption is a single atomic
statement that cannot over-consume under concurrent boots.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AgentEnrollmentToken

#: Prefix on every minted token. Exists so secret scanners and log redaction
#: have a stable thing to match — see the rule in `.gitleaks.toml`, which is
#: pinned against this constant by tests/build.
TOKEN_PREFIX = "cbe_"

#: Bytes of entropy behind the prefix.
_TOKEN_BYTES = 32

#: An hour rather than minutes: the realistic path is a human pasting the value
#: into a launch template or a secrets store, not a script consuming it
#: immediately (design §4).
DEFAULT_TTL_SECONDS = 3600
MAX_TTL_SECONDS = 24 * 3600


def hash_token(token: str) -> str:
    """SHA-256 of `token`, hex. Mirrors `user_service._hash_token`."""
    return hashlib.sha256(token.encode()).hexdigest()


def _mint_plaintext() -> str:
    """A fresh token: the prefix plus 32 random bytes, base64url, unpadded."""
    raw = secrets.token_bytes(_TOKEN_BYTES)
    return TOKEN_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass(frozen=True)
class ConsumedToken:
    """What one successful consumption grants, read off the row as it was spent.

    Carries `created_by_user_id` because auto-approval needs an approver: the
    operator who minted the token is the person who authorised every agent it
    enrolls, and recording anyone else — or nobody — would make the audit trail
    say something untrue.
    """

    id: int
    endpoint_url: str
    capabilities: dict[str, Any]
    created_by_user_id: int | None


def mint_token(
    db: Session,
    *,
    label: str,
    endpoint_url: str,
    capabilities: dict[str, Any],
    ttl_seconds: int,
    max_uses: int,
    created_by_user_id: int | None,
) -> tuple[str, AgentEnrollmentToken]:
    """Create a token, returning `(plaintext, row)`.

    The plaintext reaches exactly one caller and is never recoverable
    afterwards — the row holds only its hash. Raises `ValueError` when the TTL
    or `max_uses` falls outside its declared bounds; the caller turns that into
    a 400. Validating here rather than only in the request schema means the CLI
    and any future caller inherit the same bounds.

    Does not commit: the caller owns the transaction, so a mint and the audit
    entry recording it either both land or neither does.
    """
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    if max_uses < 1:
        raise ValueError("max_uses must be at least 1")

    plaintext = _mint_plaintext()
    row = AgentEnrollmentToken(
        token_hash=hash_token(plaintext),
        label=label,
        endpoint_url=endpoint_url,
        capabilities=capabilities,
        max_uses=max_uses,
        uses=0,
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.flush()
    return plaintext, row


def list_tokens(db: Session) -> list[AgentEnrollmentToken]:
    """Every token, newest first.

    Revoked and expired rows are included rather than filtered: an operator
    auditing what was minted needs to see the ones that are no longer live, and
    a spent token still names the agents that came through it.
    """
    return list(
        db.execute(
            select(AgentEnrollmentToken).order_by(
                AgentEnrollmentToken.created_at.desc(), AgentEnrollmentToken.id.desc()
            )
        )
        .scalars()
        .all()
    )


def consume_token(db: Session, token: str) -> ConsumedToken | None:
    """Spend one use of `token`, or return None.

    One atomic statement, deliberately. A read-then-write would let two
    machines booting from the same launch template both observe
    `uses < max_uses` before either wrote, and both enroll — over-consuming a
    token whose whole purpose is to bound how many agents it can create. The
    WHERE clause carries every liveness condition so the database decides, not
    this process: Postgres re-evaluates it against the just-committed row for
    whichever caller waited on the other's row lock.

    Returns None for **every** failure — unknown, spent, revoked, expired. The
    caller must not be able to distinguish them, and neither can it from here:
    the token path is not an oracle for live tokens (design §4).
    """
    row = db.execute(
        text(
            """
            UPDATE agent_enrollment_tokens
               SET uses = uses + 1
             WHERE token_hash = :hash
               AND uses < max_uses
               AND revoked_at IS NULL
               AND expires_at > now()
         RETURNING id, endpoint_url, capabilities, created_by_user_id
            """
        ),
        {"hash": hash_token(token)},
    ).first()
    if row is None:
        return None
    return ConsumedToken(
        id=row.id,
        endpoint_url=row.endpoint_url,
        capabilities=dict(row.capabilities or {}),
        created_by_user_id=row.created_by_user_id,
    )


def revoke_token(db: Session, token_id: int) -> AgentEnrollmentToken | None:
    """Mark `token_id` revoked, or return None when it does not exist.

    Revoking does not disturb agents already enrolled through it — they hold
    their own device identity and never present the token again. It is not a
    delete: `agents.enrollment_token_id` has to stay resolvable.

    Re-revoking is a no-op rather than an error. The first `revoked_at` is the
    honest one, and an operator clicking twice should not be told they failed.
    """
    row = db.get(AgentEnrollmentToken, token_id)
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        db.flush()
    return row
