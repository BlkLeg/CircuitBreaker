from datetime import UTC, datetime

import pytest

from app.core.errors import ValidationError
from app.db.models import Hardware, MetricAlertRule, MetricAlertState
from app.schemas.metric_alerts import MetricAlertRuleCreate, MetricAlertRuleUpdate
from app.services.monitoring import metric_rules
from app.services.monitoring.metric_evaluator import EvaluationDecision
from app.services.monitoring.metric_rules import create_rule, validate_metric_rule


def _payload(target_id, **changes):
    values = {
        "name": "High CPU",
        "target_type": "hardware",
        "target_id": target_id,
        "metric_key": "cpu_pct",
        "comparator": ">=",
        "threshold": 80,
        "unit": "%",
        "breach_duration_s": 60,
        "recovery_threshold": 70,
        "recovery_duration_s": 60,
        "max_gap_s": 90,
        "freshness_s": 120,
        "enabled": False,
    }
    values.update(changes)
    return MetricAlertRuleCreate(**values)


def test_rule_validation_rejects_unit_and_hysteresis_mismatches(db_session, factories):
    hardware = factories.hardware()
    with pytest.raises(ValidationError, match="metric and unit"):
        validate_metric_rule(db_session, _payload(hardware.id, unit="ms"))
    with pytest.raises(ValidationError, match="Recovery"):
        validate_metric_rule(db_session, _payload(hardware.id, recovery_threshold=90))


def test_enabled_rule_requires_available_destination(db_session, factories):
    hardware = factories.hardware()
    with pytest.raises(ValidationError, match="destination"):
        validate_metric_rule(db_session, _payload(hardware.id, enabled=True))


def test_create_rule_persists_separate_runtime_state(db_session, factories):
    from app.db.models import MetricAlertState

    actor = factories.user(role="admin")
    hardware = factories.hardware()
    result = create_rule(db_session, _payload(hardware.id), actor_id=actor.id)
    state = db_session.get(MetricAlertState, result.id)
    assert result.revision == 1
    assert state.assessment == "disabled"


def test_a_persisted_transition_records_why_it_reached_that_assessment(db_session):
    """The list surface cannot explain "Not evaluating" without this.

    The evaluator distinguishes no_samples, stale_samples and sample_gap -- three
    different fixes -- and every one of them surfaced as assessment `unknown`
    with the reason discarded at the end of the evaluation.
    """
    db = db_session
    hardware = Hardware(name="host")
    db.add(hardware)
    db.commit()
    rule = metric_rules.create_rule(
        db,
        MetricAlertRuleCreate(
            name="CPU hot",
            target_type="hardware",
            target_id=hardware.id,
            metric_key="cpu_pct",
            comparator=">",
            threshold=90,
            unit="%",
            recovery_threshold=80,
            enabled=False,
        ),
        actor_id=None,
    )
    db.commit()

    now = datetime.now(UTC)
    decision = EvaluationDecision(
        assessment="unknown",
        reason_code="stale_samples",
        pending_since=None,
        recovery_since=None,
        open_incident_id=None,
        last_sample_at=None,
    )
    stored = db.get(MetricAlertRule, rule.id)
    metric_rules.persist_rule_transition(db, stored, decision, now=now)
    db.commit()

    assert db.get(MetricAlertState, rule.id).reason_code == "stale_samples"
    assert metric_rules.get_rule(db, rule.id).reason_code == "stale_samples"


def test_a_rule_that_has_never_been_evaluated_reports_no_reason(db_session):
    db = db_session
    hardware = Hardware(name="host2")
    db.add(hardware)
    db.commit()
    rule = metric_rules.create_rule(
        db,
        MetricAlertRuleCreate(
            name="Never run",
            target_type="hardware",
            target_id=hardware.id,
            metric_key="cpu_pct",
            comparator=">",
            threshold=90,
            unit="%",
            recovery_threshold=80,
            enabled=False,
        ),
        actor_id=None,
    )
    db.commit()

    out = metric_rules.get_rule(db, rule.id)

    assert out.assessment == "disabled"
    assert out.reason_code == "disabled"


def test_editing_a_rule_clears_the_reason_it_no_longer_stands_behind(db_session):
    db = db_session
    hardware = Hardware(name="host3")
    db.add(hardware)
    db.commit()
    payload = MetricAlertRuleCreate(
        name="CPU hot",
        target_type="hardware",
        target_id=hardware.id,
        metric_key="cpu_pct",
        comparator=">",
        threshold=90,
        unit="%",
        recovery_threshold=80,
        enabled=False,
    )
    rule = metric_rules.create_rule(db, payload, actor_id=None)
    db.commit()
    stored = db.get(MetricAlertRule, rule.id)
    metric_rules.persist_rule_transition(
        db,
        stored,
        EvaluationDecision(
            assessment="unknown",
            reason_code="sample_gap",
            pending_since=None,
            recovery_since=None,
            open_incident_id=None,
            last_sample_at=None,
        ),
        now=datetime.now(UTC),
    )
    db.commit()

    updated = metric_rules.update_rule(
        db,
        rule.id,
        MetricAlertRuleUpdate(**payload.model_dump(), revision=rule.revision),
    )
    db.commit()

    # The rule changed; the old reason described the old rule.
    assert updated.reason_code == "disabled"
