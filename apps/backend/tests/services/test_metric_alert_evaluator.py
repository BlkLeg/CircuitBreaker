from datetime import UTC, datetime, timedelta

from app.services.monitoring.metric_catalog import MetricSample
from app.services.monitoring.metric_evaluator import PriorState, RuleConfig, evaluate_rule

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _config(**changes):
    values = {
        "enabled": True,
        "comparator": ">=",
        "threshold": 80.0,
        "breach_duration_s": 60,
        "recovery_threshold": 70.0,
        "recovery_duration_s": 60,
        "max_gap_s": 90,
        "freshness_s": 120,
    }
    values.update(changes)
    return RuleConfig(**values)


def _sample(seconds_ago, value, sample_id):
    return MetricSample(NOW - timedelta(seconds=seconds_ago), value, sample_id)


def test_single_or_duplicate_sample_cannot_prove_duration():
    sample = _sample(0, 90, "same")
    decision = evaluate_rule(_config(), PriorState(), [sample, sample], NOW)
    assert decision.assessment == "pending"
    assert decision.event_type is None


def test_sustained_breach_fires_once():
    samples = [_sample(60, 85, "one"), _sample(0, 90, "two")]
    decision = evaluate_rule(_config(), PriorState(), samples, NOW)
    assert decision.assessment == "firing"
    assert decision.event_type == "firing"


def test_stale_samples_are_unknown_and_preserve_open_incident():
    decision = evaluate_rule(
        _config(),
        PriorState(assessment="firing", open_incident_id="incident"),
        [_sample(121, 20, "old")],
        NOW,
    )
    assert decision.assessment == "unknown"
    assert decision.open_incident_id == "incident"
    assert decision.event_type is None


def test_recovery_requires_its_own_sustained_duration():
    prior = PriorState(assessment="firing", open_incident_id="incident")
    recovering = evaluate_rule(_config(), prior, [_sample(0, 60, "one")], NOW)
    recovered = evaluate_rule(
        _config(), prior, [_sample(60, 65, "one"), _sample(0, 60, "two")], NOW
    )
    assert recovering.assessment == "recovering"
    assert recovering.event_type is None
    assert recovered.assessment == "normal"
    assert recovered.event_type == "recovered"


def test_threshold_equality_follows_selected_comparator():
    samples = [_sample(0, 80, "one")]
    assert (
        evaluate_rule(_config(breach_duration_s=0), PriorState(), samples, NOW).event_type
        == "firing"
    )
    assert (
        evaluate_rule(
            _config(comparator=">", breach_duration_s=0), PriorState(), samples, NOW
        ).assessment
        == "normal"
    )
