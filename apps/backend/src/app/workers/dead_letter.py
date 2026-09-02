"""Bounded redelivery for JetStream consumers (route F14).

Both consumers used to `nak()` every failure with no `max_deliver`, so a message
that can never succeed was redelivered forever and its consumer made no
progress. `monitor_poll_worker` makes that worse by naking the whole batch on one
failure, so a single poison message blocks every good message beside it.

The fix is a pair, and neither half works alone. `max_deliver` on the consumer
bounds the retries; this module decides what happens when the budget runs out.
Bounding without parking would swap an infinite loop for a silent drop — the
operator still learns nothing, and now the payload is gone as well.

One module rather than a copy in each worker: the two must agree on when a
message is beyond saving, and a divergence there is exactly the kind that is
found in production rather than review.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.services.failed_message_service import park_message

_logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session] | Iterator[Session]]


def _num_delivered(msg: Any) -> int:
    """How many times JetStream has delivered this message, best-effort.

    Returns 0 when the metadata is unavailable, which biases toward `nak` — the
    recoverable outcome. Guessing high here would park messages that still had
    attempts left.
    """
    try:
        return int(msg.metadata.num_delivered)
    except Exception:  # noqa: BLE001 - absent metadata must not decide a drop
        _logger.warning("dead_letter: message carried no delivery metadata; treating as attempt 0")
        return 0


async def _safe(coro: Any, what: str) -> None:
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 - the loop must survive a failed ack path
        _logger.warning("dead_letter: %s failed: %s", what, exc)


async def handle_failed_delivery(
    msg: Any,
    *,
    stream: str,
    consumer: str,
    error: str,
    max_deliver: int,
    session_factory: SessionFactory,
) -> bool:
    """Nak a failed message, or park and terminate it once its budget is spent.

    Returns whether the message was parked.

    Ordering is load-bearing: the row is committed **before** `term()` is sent.
    `term()` tells the server never to redeliver, so it is the moment the only
    other copy of the message disappears; a crash between an uncommitted park and
    that call would lose the payload and its record together.

    If parking fails the message is naked instead. Terminating a message we could
    not record would be the silent drop this module exists to prevent, so the
    consumer takes another lap rather than losing the work — a message that keeps
    failing to park will keep coming back, which is visible, where a drop is not.
    """
    delivered = _num_delivered(msg)
    if delivered < max_deliver:
        await _safe(msg.nak(), "nak")
        return False

    try:
        with session_factory() as db:  # type: ignore[union-attr]
            park_message(
                db,
                stream=stream,
                subject=msg.subject,
                consumer=consumer,
                payload=msg.data,
                error=error,
                delivered_count=delivered,
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001 - see the docstring: nak is the safe fallback
        _logger.error(
            "dead_letter: could not park %s after %d deliveries (%s) — naking instead",
            msg.subject,
            delivered,
            exc,
            exc_info=True,
        )
        await _safe(msg.nak(), "nak")
        return False

    _logger.error(
        "dead_letter: parked %s from %s after %d deliveries: %s",
        msg.subject,
        stream,
        delivered,
        error,
    )
    await _safe(msg.term(), "term")
    return True
