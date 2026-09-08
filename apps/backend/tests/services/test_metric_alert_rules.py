import pytest

from app.core.errors import ValidationError
from app.schemas.metric_alerts import MetricAlertRuleCreate
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
