"""Retry-safe routing and per-destination delivery receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import NotificationDelivery, NotificationRoute, NotificationSink
from app.schemas.notifications import AlertEnvelope, DeliveryOutcome, DispatchSummary
from app.services.notification_secrets import decrypt_config
from app.services.notification_severity import route_matches

_CLAIM_LEASE_SECONDS = 30
_NO_ROUTE_SINK_KEY = 0


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """Non-secret routing snapshot; ciphertext is decrypted only before I/O."""

    sink_id: int
    provider: str
    stored_config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    receipt_id: int
    owner: str
    status: Literal["claimed", "completed", "busy"]
    existing: DeliveryOutcome | None = None


Sender = Callable[[str, dict[str, Any], AlertEnvelope, int, str], Awaitable[DeliveryOutcome]]


def select_delivery_targets(db: Session, event: AlertEnvelope) -> list[TargetSnapshot]:
    """Select unique destinations while enforcing route and sink enablement."""
    if event.sink_id is not None:
        sink = (
            db.query(NotificationSink)
            .filter(
                NotificationSink.id == event.sink_id,
                NotificationSink.enabled.is_(True),
            )
            .one_or_none()
        )
        if sink is None:
            return []
        direct_config: object = sink.provider_config
        if isinstance(direct_config, str):
            try:
                direct_config = json.loads(direct_config)
            except ValueError:
                direct_config = {}
        if not isinstance(direct_config, dict):
            direct_config = {}
        return [
            TargetSnapshot(
                sink_id=sink.id,
                provider=sink.provider_type,
                stored_config=dict(direct_config),
            )
        ]
    rows = (
        db.query(NotificationRoute, NotificationSink)
        .join(NotificationSink, NotificationSink.id == NotificationRoute.sink_id)
        .filter(NotificationRoute.enabled.is_(True), NotificationSink.enabled.is_(True))
        .all()
    )
    selected: dict[int, TargetSnapshot] = {}
    for route, sink in rows:
        if not route_matches(route.alert_severity, event.severity):
            continue
        config: object = sink.provider_config
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = {}
        if not isinstance(config, dict):
            config = {}
        selected.setdefault(
            sink.id,
            TargetSnapshot(
                sink_id=sink.id,
                provider=sink.provider_type,
                stored_config=dict(config),
            ),
        )
    return list(selected.values())


def stable_event_id(msg: Any, event: AlertEnvelope) -> str:
    """Resolve a replay-stable identity, preferring producer and stream IDs."""
    if event.event_id:
        return event.event_id
    headers = getattr(msg, "headers", None) or {}
    for key in ("Nats-Msg-Id", "Nats-Msg-ID", "nats-msg-id"):
        value = headers.get(key)
        if value:
            return str(value)[:160]
    try:
        metadata = msg.metadata
        sequence = metadata.sequence.stream
        stream = getattr(metadata, "stream", None) or "CB_EVENTS"
        return f"js:{stream}:{sequence}"[:160]
    except (AttributeError, RuntimeError, TypeError):
        raw = bytes(getattr(msg, "data", b""))
        subject = str(getattr(msg, "subject", ""))
        digest = hashlib.sha256(subject.encode() + b"\0" + raw).hexdigest()
        return f"legacy:{digest}"


def _receipt_outcome(receipt: NotificationDelivery) -> DeliveryOutcome:
    state = receipt.state if receipt.state in {"accepted", "terminal"} else "retryable"
    return DeliveryOutcome(
        state=state,  # type: ignore[arg-type]
        reason_code=receipt.reason_code or "delivery_in_progress",
        safe_message=receipt.safe_message or "Delivery is already being processed.",
        provider=receipt.provider,
        sink_id=receipt.sink_id,
        event_id=receipt.event_id,
        attempt_count=receipt.attempts,
        http_status=receipt.http_status,
        retry_after=receipt.retry_after_seconds,
        accepted_at=receipt.accepted_at,
    )


def claim_delivery(
    db: Session,
    event_id: str,
    sink_key: int,
    provider: str,
    *,
    sink_id: int | None,
    owner: str,
    now: datetime,
) -> DeliveryClaim:
    """Claim a destination in a short transaction using a bounded lease."""
    statement = (
        pg_insert(NotificationDelivery)
        .values(
            event_id=event_id,
            sink_key=sink_key,
            sink_id=sink_id,
            provider=provider,
            state="pending",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "sink_key"])
    )
    db.execute(statement)
    receipt = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.event_id == event_id,
            NotificationDelivery.sink_key == sink_key,
        )
        .with_for_update()
        .one()
    )
    if receipt.state in {"accepted", "terminal"}:
        return DeliveryClaim(receipt.id, owner, "completed", _receipt_outcome(receipt))
    if receipt.claim_expires_at and receipt.claim_expires_at > now:
        wait = math.ceil((receipt.claim_expires_at - now).total_seconds())
        existing = _receipt_outcome(receipt).model_copy(update={"retry_after": wait})
        return DeliveryClaim(receipt.id, owner, "busy", existing)
    if receipt.next_retry_at and receipt.next_retry_at > now:
        wait = math.ceil((receipt.next_retry_at - now).total_seconds())
        existing = _receipt_outcome(receipt).model_copy(update={"retry_after": wait})
        return DeliveryClaim(receipt.id, owner, "busy", existing)

    receipt.state = "claimed"
    receipt.claim_owner = owner
    receipt.claim_expires_at = now + timedelta(seconds=_CLAIM_LEASE_SECONDS)
    receipt.updated_at = now
    db.flush()
    return DeliveryClaim(receipt.id, owner, "claimed")


def record_delivery_outcome(
    db: Session,
    claim: DeliveryClaim,
    outcome: DeliveryOutcome,
    *,
    now: datetime,
) -> bool:
    """Persist an outcome only while the caller still owns its claim."""
    receipt = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.id == claim.receipt_id,
            NotificationDelivery.claim_owner == claim.owner,
        )
        .with_for_update()
        .first()
    )
    if receipt is None:
        return False
    receipt.state = outcome.state
    receipt.attempts += outcome.attempt_count
    receipt.reason_code = outcome.reason_code[:64]
    receipt.safe_message = outcome.safe_message[:300]
    receipt.http_status = outcome.http_status
    receipt.retry_after_seconds = outcome.retry_after
    receipt.accepted_at = outcome.accepted_at
    receipt.next_retry_at = (
        now + timedelta(seconds=outcome.retry_after or 0) if outcome.state == "retryable" else None
    )
    receipt.claim_owner = None
    receipt.claim_expires_at = None
    receipt.updated_at = now
    db.flush()
    return True


def _summarize(event_id: str, outcomes: list[DeliveryOutcome]) -> DispatchSummary:
    accepted = sum(outcome.state == "accepted" for outcome in outcomes)
    terminal = sum(outcome.state == "terminal" for outcome in outcomes)
    retryable = sum(outcome.state == "retryable" for outcome in outcomes)
    state = "retryable" if retryable else "accepted" if accepted else "terminal"
    return DispatchSummary(
        event_id=event_id,
        state=state,  # type: ignore[arg-type]
        target_count=sum(outcome.provider != "routing" for outcome in outcomes),
        accepted_count=accepted,
        terminal_count=terminal,
        retryable_count=retryable,
        outcomes=outcomes,
    )


async def dispatch_event(
    event: AlertEnvelope,
    event_id: str,
    *,
    session_factory: Callable[[], Any],
    sender: Sender,
    owner: str | None = None,
) -> DispatchSummary:
    """Claim, send concurrently without DB locks, and persist each result."""
    claim_owner = owner or f"notification-worker:{uuid4()}"
    with session_factory() as db:
        targets = select_delivery_targets(db, event)

    if not targets:
        now = datetime.now(UTC)
        with session_factory() as db:
            claim = claim_delivery(
                db,
                event_id,
                _NO_ROUTE_SINK_KEY,
                "routing",
                sink_id=None,
                owner=claim_owner,
                now=now,
            )
            db.commit()
        if claim.existing is not None:
            return _summarize(event_id, [claim.existing])
        outcome = DeliveryOutcome(
            state="terminal",
            reason_code="no_route",
            safe_message="No enabled notification destination matched this alert.",
            provider="routing",
            event_id=event_id,
            attempt_count=0,
        )
        with session_factory() as db:
            record_delivery_outcome(db, claim, outcome, now=datetime.now(UTC))
            db.commit()
        return _summarize(event_id, [outcome])

    pending: list[tuple[TargetSnapshot, DeliveryClaim]] = []
    outcomes: list[DeliveryOutcome] = []
    for target in targets:
        with session_factory() as db:
            claim = claim_delivery(
                db,
                event_id,
                target.sink_id,
                target.provider,
                sink_id=target.sink_id,
                owner=claim_owner,
                now=datetime.now(UTC),
            )
            db.commit()
        if claim.status == "claimed":
            pending.append((target, claim))
        elif claim.existing is not None:
            outcomes.append(claim.existing)

    async def send_target(target: TargetSnapshot) -> DeliveryOutcome:
        # Routing selection and network I/O cannot share a DB transaction. A
        # second short read closes the disable/delete race without holding a
        # lock while calling the provider.
        with session_factory() as db:
            current = (
                db.query(NotificationSink)
                .filter(
                    NotificationSink.id == target.sink_id,
                    NotificationSink.enabled.is_(True),
                )
                .first()
            )
            matching_routes = (
                db.query(NotificationRoute)
                .filter(
                    NotificationRoute.sink_id == target.sink_id,
                    NotificationRoute.enabled.is_(True),
                )
                .all()
                if current is not None
                else []
            )
            eligible = current is not None and (
                event.sink_id == target.sink_id
                or any(
                    route_matches(route.alert_severity, event.severity) for route in matching_routes
                )
            )
            current_config: object = current.provider_config if current else {}
        if not eligible:
            return DeliveryOutcome(
                state="terminal",
                reason_code="destination_unavailable",
                safe_message="The destination was disabled or removed before delivery.",
                provider=target.provider,
                sink_id=target.sink_id,
                event_id=event_id,
                attempt_count=0,
            )
        if isinstance(current_config, str):
            try:
                current_config = json.loads(current_config)
            except ValueError:
                current_config = {}
        if not isinstance(current_config, dict):
            current_config = {}
        try:
            config = decrypt_config(current_config)
        except Exception as exc:
            name = type(exc).__name__.lower()
            reason = "authentication_rejected" if "token" in name else "credential_unavailable"
            return DeliveryOutcome(
                state="terminal",
                reason_code=reason,
                safe_message="Destination credentials are unavailable.",
                provider=target.provider,
                sink_id=target.sink_id,
                event_id=event_id,
                attempt_count=0,
            )
        return await sender(target.provider, config, event, target.sink_id, event_id)

    sent = await asyncio.gather(
        *(send_target(target) for target, _claim in pending), return_exceptions=True
    )
    for (target, claim), result in zip(pending, sent):
        if isinstance(result, BaseException):
            if isinstance(result, asyncio.CancelledError):
                raise result
            result = DeliveryOutcome(
                state="retryable",
                reason_code="delivery_error",
                safe_message="Delivery failed before the provider accepted it.",
                provider=target.provider,
                sink_id=target.sink_id,
                event_id=event_id,
                attempt_count=1,
            )
        with session_factory() as db:
            persisted = record_delivery_outcome(db, claim, result, now=datetime.now(UTC))
            db.commit()
        if persisted:
            outcomes.append(result)
        else:
            outcomes.append(
                DeliveryOutcome(
                    state="retryable",
                    reason_code="claim_lost",
                    safe_message="Delivery ownership expired before its result was recorded.",
                    provider=target.provider,
                    sink_id=target.sink_id,
                    event_id=event_id,
                    attempt_count=result.attempt_count,
                )
            )

    return _summarize(event_id, outcomes)
