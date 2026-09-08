"""Validation, CRUD, preview, and persisted metric-alert transitions."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.time import utcnow
from app.db.models import (
    MetricAlertEvent,
    MetricAlertRule,
    MetricAlertState,
    NotificationSink,
)
from app.schemas.metric_alerts import (
    MetricAlertPreview,
    MetricAlertRuleCreate,
    MetricAlertRuleOut,
    MetricAlertRuleUpdate,
)
from app.services.monitoring.metric_catalog import CATALOG, read_metric_window, validate_target
from app.services.monitoring.metric_evaluator import (
    EvaluationDecision,
    PriorState,
    RuleConfig,
    evaluate_rule,
)


def validate_metric_rule(db: Session, payload: MetricAlertRuleCreate) -> None:
    definition = CATALOG.get(payload.metric_key)
    if definition is None or payload.unit != definition.unit:
        raise ValidationError("The metric and unit combination is not supported.")
    if payload.comparator not in definition.comparators:
        raise ValidationError("The comparator is not supported for this metric.")
    if not math.isfinite(payload.threshold) or not math.isfinite(payload.recovery_threshold):
        raise ValidationError("Thresholds must be finite numbers.")
    if payload.comparator in {">", ">="} and payload.recovery_threshold > payload.threshold:
        raise ValidationError("Recovery must be at or below the firing threshold.")
    if payload.comparator in {"<", "<="} and payload.recovery_threshold < payload.threshold:
        raise ValidationError("Recovery must be at or above the firing threshold.")
    try:
        validate_target(db, payload.target_type, payload.target_id)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if payload.enabled:
        if payload.sink_id is None:
            raise ValidationError("An enabled metric rule requires a notification destination.")
        sink = db.get(NotificationSink, payload.sink_id)
        if sink is None or not sink.enabled:
            raise ValidationError("The selected notification destination is unavailable.")


def _out(rule: MetricAlertRule, state: MetricAlertState | None) -> MetricAlertRuleOut:
    item = MetricAlertRuleOut.model_validate(rule)
    item.assessment = state.assessment if state else ("disabled" if not rule.enabled else "unknown")
    item.open_incident_id = state.open_incident_id if state else None
    return item


def list_rules(db: Session) -> list[MetricAlertRuleOut]:
    states = {state.rule_id: state for state in db.query(MetricAlertState).all()}
    return [
        _out(rule, states.get(rule.id))
        for rule in db.query(MetricAlertRule)
        .order_by(MetricAlertRule.name, MetricAlertRule.id)
        .all()
    ]


def get_rule(db: Session, rule_id: int) -> MetricAlertRuleOut:
    rule = db.get(MetricAlertRule, rule_id)
    if rule is None:
        raise NotFoundError("Metric alert rule not found.")
    return _out(rule, db.get(MetricAlertState, rule.id))


def create_rule(
    db: Session, payload: MetricAlertRuleCreate, *, actor_id: int | None
) -> MetricAlertRuleOut:
    validate_metric_rule(db, payload)
    rule = MetricAlertRule(**payload.model_dump(), created_by=actor_id, revision=1)
    db.add(rule)
    db.flush()
    state = MetricAlertState(
        rule_id=rule.id,
        rule_revision=rule.revision,
        assessment="unknown" if rule.enabled else "disabled",
    )
    db.add(state)
    db.flush()
    return _out(rule, state)


def update_rule(db: Session, rule_id: int, payload: MetricAlertRuleUpdate) -> MetricAlertRuleOut:
    rule = (
        db.query(MetricAlertRule)
        .filter(MetricAlertRule.id == rule_id)
        .with_for_update()
        .one_or_none()
    )
    if rule is None:
        raise NotFoundError("Metric alert rule not found.")
    if rule.revision != payload.revision:
        raise ConflictError("The rule changed; reload it and try again.", error_code="stale_rule")
    validate_metric_rule(db, payload)
    for key, value in payload.model_dump(exclude={"revision"}).items():
        setattr(rule, key, value)
    rule.revision += 1
    state = db.get(MetricAlertState, rule.id)
    if state is None:
        state = MetricAlertState(rule_id=rule.id, rule_revision=rule.revision)
        db.add(state)
    state.rule_revision = rule.revision
    state.assessment = "unknown" if rule.enabled else "disabled"
    state.pending_since = None
    state.recovery_since = None
    # Disabling/editing does not fabricate recovery. Preserve an open incident.
    state.last_sample_at = None
    db.flush()
    return _out(rule, state)


def delete_rule(db: Session, rule_id: int) -> None:
    rule = db.get(MetricAlertRule, rule_id)
    if rule is None:
        raise NotFoundError("Metric alert rule not found.")
    db.delete(rule)
    db.flush()


def _config(rule: MetricAlertRule | MetricAlertRuleCreate) -> RuleConfig:
    return RuleConfig(
        enabled=rule.enabled,
        comparator=rule.comparator,
        threshold=rule.threshold,
        breach_duration_s=rule.breach_duration_s,
        recovery_threshold=rule.recovery_threshold,
        recovery_duration_s=rule.recovery_duration_s,
        max_gap_s=rule.max_gap_s,
        freshness_s=rule.freshness_s,
    )


def preview_rule(
    db: Session, payload: MetricAlertRuleCreate, *, window_seconds: int
) -> MetricAlertPreview:
    validate_metric_rule(db, payload)
    now = utcnow()
    samples = read_metric_window(
        db,
        target_id=payload.target_id,
        metric_key=payload.metric_key,
        source=payload.source,
        since=now - timedelta(seconds=window_seconds),
    )
    decision = evaluate_rule(_config(payload), PriorState(), samples, now)
    return MetricAlertPreview(
        assessment=decision.assessment,
        reason_code=decision.reason_code,
        sample_count=len(samples),
        window_start=samples[0].timestamp if samples else None,
        window_end=samples[-1].timestamp if samples else None,
        limitations=["Preview uses retained raw samples and sends no notification."],
        would_emit=decision.event_type,
    )


def persist_rule_transition(
    db: Session,
    rule: MetricAlertRule,
    decision: EvaluationDecision,
    *,
    now: datetime,
) -> MetricAlertEvent | None:
    state = (
        db.query(MetricAlertState)
        .filter(MetricAlertState.rule_id == rule.id)
        .with_for_update()
        .one_or_none()
    )
    if state is None:
        state = MetricAlertState(rule_id=rule.id, rule_revision=rule.revision)
        db.add(state)
    if state.rule_revision != rule.revision:
        state.rule_revision = rule.revision
        state.pending_since = None
        state.recovery_since = None
    incident_id = state.open_incident_id
    if decision.event_type == "firing":
        incident_id = uuid4().hex
    elif decision.event_type == "recovered" and not incident_id:
        return None
    state.assessment = decision.assessment
    state.pending_since = decision.pending_since
    state.recovery_since = decision.recovery_since
    state.open_incident_id = incident_id if decision.assessment != "normal" else None
    state.last_sample_at = decision.last_sample_at
    state.last_evaluated_at = now
    if decision.event_type is None or incident_id is None:
        return None
    transition_key = f"metric:{rule.id}:{rule.revision}:{incident_id}:{decision.event_type}"
    event = MetricAlertEvent(
        id=uuid4().hex,
        transition_key=transition_key,
        rule_id=rule.id,
        rule_revision=rule.revision,
        incident_id=incident_id,
        event_type=decision.event_type,
        occurred_at=now,
        payload={
            "title": f"Metric alert {rule.name} {decision.event_type}",
            "message": f"{rule.metric_key} on hardware:{rule.target_id} is {decision.assessment}.",
            "severity": rule.severity if decision.event_type == "firing" else "info",
            "metric_rule_id": rule.id,
            "incident_id": incident_id,
            "status": decision.event_type,
            "sink_id": rule.sink_id,
            "occurred_at": now.isoformat(),
        },
    )
    db.add(event)
    return event


def evaluate_persisted_rule(
    db: Session, rule: MetricAlertRule, *, now: datetime
) -> MetricAlertEvent | None:
    window = max(rule.breach_duration_s, rule.recovery_duration_s) + rule.max_gap_s
    samples = read_metric_window(
        db,
        target_id=rule.target_id,
        metric_key=rule.metric_key,
        source=rule.source,
        since=now - timedelta(seconds=max(window, rule.freshness_s)),
    )
    state = db.get(MetricAlertState, rule.id)
    prior = PriorState(
        assessment=state.assessment if state else "unknown",
        open_incident_id=state.open_incident_id if state else None,
    )
    decision = evaluate_rule(_config(rule), prior, samples, now)
    return persist_rule_transition(db, rule, decision, now=now)
