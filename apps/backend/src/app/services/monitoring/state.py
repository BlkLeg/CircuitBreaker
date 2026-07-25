"""Monitor state machine: up/pending/down transitions and event persistence.

decide() is pure and fully unit-testable. apply_result() locks the monitor row
(FOR UPDATE — safe across the 2 poll-worker replicas), applies the decision,
reschedules retries sooner than the base interval, and appends a MonitorEvent
on every transition. The caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import MonitorEvent, MonitorItem

UP = "up"
DOWN = "down"
PENDING = "pending"
MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class StateDecision:
    new_status: str
    retries: int
    event_type: str | None  # None → no transition, nothing recorded
    notify: str | None  # "down" | "recovered" | None


@dataclass(frozen=True)
class AppliedTransition:
    item_id: int
    name: str
    status_from: str | None
    status_to: str
    msg: str
    notify: str | None
    occurred_at: datetime


def decide(prev_status: str | None, prev_retries: int, up: bool, max_retries: int) -> StateDecision:
    if up:
        if prev_status == UP:
            return StateDecision(UP, 0, None, None)
        notify = "recovered" if prev_status == DOWN else None
        return StateDecision(UP, 0, "up", notify)

    retries = prev_retries + 1
    if prev_status != DOWN and retries <= max_retries:
        event = "pending" if prev_status != PENDING else None
        return StateDecision(PENDING, retries, event, None)
    if prev_status == DOWN:
        return StateDecision(DOWN, retries, None, None)
    return StateDecision(DOWN, retries, "down", "down")


def apply_result(
    db: Session, item_id: int, up: bool, msg: str, checked_at: datetime
) -> AppliedTransition | None:
    item = db.query(MonitorItem).filter(MonitorItem.id == item_id).with_for_update().one_or_none()
    if item is None:
        return None

    decision = decide(item.last_status, item.consecutive_failures, up, item.max_retries)

    item.last_polled_at = checked_at
    item.consecutive_failures = decision.retries
    prev_status = item.last_status

    # Retrying: pull the next check in sooner than the scheduler's base advance.
    if decision.new_status == PENDING:
        retry_in = item.retry_interval_secs or item.interval_secs
        item.next_due_at = checked_at + timedelta(seconds=retry_in)

    if decision.event_type is None:
        item.last_status = decision.new_status
        return None

    duration_secs = None
    if item.last_status_change_at is not None:
        duration_secs = round((checked_at - item.last_status_change_at).total_seconds(), 1)

    item.last_status = decision.new_status
    item.last_status_change_at = checked_at
    db.add(
        MonitorEvent(
            item_id=item.id,
            event_type=decision.event_type,
            status_from=prev_status,
            status_to=decision.new_status,
            msg=msg[:2000],
            duration_secs=duration_secs,
        )
    )
    return AppliedTransition(
        item_id=item.id,
        name=item.name,
        status_from=prev_status,
        status_to=decision.new_status,
        msg=msg,
        notify=decision.notify,
        occurred_at=checked_at,
    )


__all__ = [
    "UP",
    "DOWN",
    "PENDING",
    "MAINTENANCE",
    "StateDecision",
    "AppliedTransition",
    "decide",
    "apply_result",
]
