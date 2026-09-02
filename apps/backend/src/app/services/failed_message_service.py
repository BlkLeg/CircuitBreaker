"""Park, list, requeue and discard poisoned JetStream work (route F14).

The service deliberately does **not** publish to NATS. Republishing is async and
this module is called from sync `Session` contexts — the workers park from
inside their own session, and the operator routes hold a `Depends(get_db)`
session. Mixing an `await` into that would force every caller async for one I/O
call.

Instead `requeue` marks the row and returns a `Republish` describing what to
send. The caller — which already owns a NATS connection — does the publishing.
That also keeps the database decision and the network effect separable: the row
is marked in the same transaction the caller controls, so a publish failure can
roll it back rather than leaving a row claiming a requeue that never happened.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models_failed_message import FailedMessage


class FailedMessageError(Exception):
    """Base for operator-action failures on a parked message."""


class MessageNotFound(FailedMessageError):
    """No parked message with the given id."""


class MessageAlreadyResolved(FailedMessageError):
    """The message was already requeued or discarded.

    Raised rather than ignored so a double submission from the operator page is
    reported instead of silently republishing the same work twice — a duplicate
    that looks like success is the worst outcome for a recovery tool.
    """


class RepublishFailed(FailedMessageError):
    """The message was not put back on its stream, so the row was not marked."""


@dataclass(frozen=True)
class Republish:
    """What must be sent to put a parked message back on its stream."""

    subject: str
    payload: bytes


Publisher = Callable[[str, bytes], Awaitable[None]]


def park_message(
    db: Session,
    *,
    stream: str,
    subject: str,
    consumer: str,
    payload: bytes,
    error: str,
    delivered_count: int,
) -> FailedMessage:
    """Record a message that exhausted its delivery budget.

    Does not commit: the worker that calls this owns the transaction and needs
    the park and the message's termination to succeed or fail together.
    """
    row = FailedMessage(
        stream=stream,
        subject=subject,
        consumer=consumer,
        payload=payload,
        error=error,
        delivered_count=delivered_count,
    )
    db.add(row)
    db.flush()
    return row


def list_parked(db: Session, *, include_resolved: bool = False) -> list[FailedMessage]:
    """Parked messages, newest first.

    Newest first because an operator meeting this page is usually triaging a
    flood that just started, and the useful rows are the recent ones.
    """
    query = db.query(FailedMessage)
    if not include_resolved:
        query = query.filter(
            FailedMessage.requeued_at.is_(None),
            FailedMessage.discarded_at.is_(None),
        )
    return list(query.order_by(FailedMessage.id.desc()).all())


def _load_actionable(db: Session, message_id: int) -> FailedMessage:
    row = db.get(FailedMessage, message_id)
    if row is None:
        raise MessageNotFound(f"no parked message with id {message_id}")
    if row.is_resolved:
        raise MessageAlreadyResolved(f"message {message_id} was already requeued or discarded")
    return row


def requeue(db: Session, message_id: int) -> Republish:
    """Mark a parked message for redelivery and return what to republish.

    Marks and flushes only — the caller owns the commit. `requeue_and_publish`
    is the operator-facing wrapper that also sends it.
    """
    row = _load_actionable(db, message_id)
    row.requeued_at = utcnow()
    db.flush()
    return Republish(subject=row.subject, payload=row.payload)


async def requeue_and_publish(db: Session, message_id: int, publish: Publisher) -> FailedMessage:
    """Put a parked message back on its stream, marking the row only if it lands.

    The publish happens between the flush and the commit so the two outcomes
    cannot disagree: if it raises, the mark is rolled back and the row stays
    parked for another attempt, rather than claiming a requeue that never
    reached a stream.

    A caveat worth knowing, because it bounds what this guarantee is worth:
    `nats_client.publish` buffers on a disconnect and logs rather than raising,
    so a requeue issued while NATS is down is recorded as done and delivered
    when the connection returns — or dropped silently if the buffer overflows
    first. The rollback below therefore covers a publisher that genuinely
    raises, not every way a message can fail to arrive.
    """
    republish = requeue(db, message_id)
    try:
        await publish(republish.subject, republish.payload)
    except Exception as exc:
        db.rollback()
        raise RepublishFailed(f"could not republish message {message_id}: {exc}") from exc
    db.commit()
    row = db.get(FailedMessage, message_id)
    if row is None:  # pragma: no cover - the row was just committed
        raise MessageNotFound(f"no parked message with id {message_id}")
    return row


def discard(db: Session, message_id: int) -> FailedMessage:
    """Mark a parked message as deliberately abandoned, and commit.

    The row survives. "This failed and was thrown away" is a different fact from
    "this never happened", and the difference matters when the same message
    parks again.
    """
    row = _load_actionable(db, message_id)
    row.discarded_at = utcnow()
    db.commit()
    db.refresh(row)
    return row
