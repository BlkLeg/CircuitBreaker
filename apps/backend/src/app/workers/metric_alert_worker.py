"""Bounded scheduled metric evaluation and persisted-event publication."""

from __future__ import annotations

import logging

from app.core.nats_client import nats_client
from app.core.subjects import METRIC_ALERT_EVENT
from app.core.time import utcnow
from app.db.models import MetricAlertEvent, MetricAlertRule
from app.db.session import SessionLocal
from app.services.monitoring.metric_rules import evaluate_persisted_rule

logger = logging.getLogger(__name__)


def evaluate_due_rules(*, limit: int = 100) -> int:
    now = utcnow()
    with SessionLocal() as db:
        rules = (
            db.query(MetricAlertRule)
            .filter(MetricAlertRule.enabled.is_(True))
            .order_by(MetricAlertRule.id)
            .limit(limit)
            .all()
        )
        for rule in rules:
            evaluate_persisted_rule(db, rule, now=now)
        db.commit()
        return len(rules)


async def publish_pending_metric_events(*, limit: int = 100) -> int:
    published = 0
    with SessionLocal() as db:
        events = (
            db.query(MetricAlertEvent)
            .filter(MetricAlertEvent.publish_state == "pending")
            .order_by(MetricAlertEvent.occurred_at)
            .limit(limit)
            .all()
        )
        for event in events:
            event.publish_attempts += 1
            try:
                accepted = await nats_client.js_publish(
                    METRIC_ALERT_EVENT.format(rule_id=event.rule_id),
                    event.payload,
                    msg_id=event.transition_key,
                )
                if not accepted:
                    continue
            except Exception:
                logger.exception("Metric alert event %s publish failed", event.id)
                continue
            event.publish_state = "published"
            event.published_at = utcnow()
            db.commit()
            published += 1
        return published


async def run_metric_alert_job() -> None:
    evaluate_due_rules()
    await publish_pending_metric_events()
