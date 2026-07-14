"""Atomically claim due monitor items and enqueue poll messages.

The claim is a single UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)
RETURNING statement: it selects due rows, advances next_due_at (with small jitter
so a post-downtime burst spreads out), and returns the claimed rows — all in one
round-trip. This makes double-enqueue impossible and is safe across concurrent
schedulers (SKIP LOCKED), though normally only one runs (advisory lock).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.subjects import MONITOR_POLL_ITEM

logger = logging.getLogger(__name__)

_CLAIM_SQL = text(
    """
    UPDATE monitor_items
    SET next_due_at = now()
        + make_interval(secs => interval_secs)
        + make_interval(secs => random() * least(interval_secs, 5)),
        updated_at = now()
    WHERE id IN (
        SELECT id FROM monitor_items
        WHERE enabled AND next_due_at <= now()
        ORDER BY next_due_at
        FOR UPDATE SKIP LOCKED
        LIMIT :batch
    )
    RETURNING id, target_type, target_id, host, check_type, params, interval_secs
    """
)


def claim_due_items(db: Session, batch: int = 200) -> list[dict]:
    rows = db.execute(_CLAIM_SQL, {"batch": batch}).mappings().all()
    db.commit()
    return [
        {
            "item_id": r["id"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "host": r["host"],
            "check_type": r["check_type"],
            "params": r["params"] or {},
            "interval_secs": r["interval_secs"],
        }
        for r in rows
    ]


async def enqueue_due(
    db: Session,
    publish: Callable[[str, dict], Awaitable[bool]],
    batch: int = 200,
) -> int:
    items = claim_due_items(db, batch=batch)
    enqueued = 0
    for item in items:
        ok = await publish(MONITOR_POLL_ITEM, item)
        if ok:
            enqueued += 1
        else:
            logger.warning("Failed to enqueue poll for item %s", item["item_id"])
    return enqueued
