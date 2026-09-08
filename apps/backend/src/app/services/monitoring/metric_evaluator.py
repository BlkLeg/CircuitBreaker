"""Pure sustained-threshold evaluator for metric alert rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.services.monitoring.metric_catalog import MetricSample

Assessment = Literal["disabled", "unknown", "normal", "pending", "firing", "recovering"]


@dataclass(frozen=True)
class RuleConfig:
    enabled: bool
    comparator: str
    threshold: float
    breach_duration_s: int
    recovery_threshold: float
    recovery_duration_s: int
    max_gap_s: int
    freshness_s: int


@dataclass(frozen=True)
class PriorState:
    assessment: str = "unknown"
    open_incident_id: str | None = None


@dataclass(frozen=True)
class EvaluationDecision:
    assessment: Assessment
    reason_code: str
    pending_since: datetime | None
    recovery_since: datetime | None
    open_incident_id: str | None
    last_sample_at: datetime | None
    event_type: Literal["firing", "recovered"] | None = None


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
    }[comparator]


def _recovered(value: float, config: RuleConfig) -> bool:
    if config.comparator in {">", ">="}:
        return value <= config.recovery_threshold
    return value >= config.recovery_threshold


def evaluate_rule(
    config: RuleConfig,
    prior: PriorState,
    samples: list[MetricSample],
    now: datetime,
) -> EvaluationDecision:
    if not config.enabled:
        return EvaluationDecision("disabled", "disabled", None, None, prior.open_incident_id, None)
    unique = {sample.sample_id: sample for sample in samples if math.isfinite(sample.value)}
    ordered = sorted(unique.values(), key=lambda sample: sample.timestamp)
    if not ordered:
        return EvaluationDecision("unknown", "no_samples", None, None, prior.open_incident_id, None)
    latest = ordered[-1]
    if (now - latest.timestamp).total_seconds() > config.freshness_s:
        return EvaluationDecision(
            "unknown", "stale_samples", None, None, prior.open_incident_id, latest.timestamp
        )
    for left, right in zip(ordered, ordered[1:], strict=False):
        if (right.timestamp - left.timestamp).total_seconds() > config.max_gap_s:
            ordered = ordered[ordered.index(right) :]
    if not ordered:
        return EvaluationDecision(
            "unknown", "sample_gap", None, None, prior.open_incident_id, latest.timestamp
        )

    predicate = (
        (lambda sample: _recovered(sample.value, config))
        if prior.open_incident_id
        else (lambda sample: _compare(sample.value, config.comparator, config.threshold))
    )
    tail: list[MetricSample] = []
    for sample in reversed(ordered):
        if not predicate(sample):
            break
        tail.append(sample)
    tail.reverse()
    if not tail:
        assessment: Assessment = "firing" if prior.open_incident_id else "normal"
        return EvaluationDecision(
            assessment, "condition_not_met", None, None, prior.open_incident_id, latest.timestamp
        )
    duration = (tail[-1].timestamp - tail[0].timestamp).total_seconds()
    if prior.open_incident_id:
        if duration >= config.recovery_duration_s:
            return EvaluationDecision(
                "normal", "recovered", None, None, None, latest.timestamp, "recovered"
            )
        return EvaluationDecision(
            "recovering",
            "recovery_duration",
            None,
            tail[0].timestamp,
            prior.open_incident_id,
            latest.timestamp,
        )
    if duration >= config.breach_duration_s:
        return EvaluationDecision(
            "firing", "threshold_duration", None, None, None, latest.timestamp, "firing"
        )
    return EvaluationDecision(
        "pending", "breach_duration", tail[0].timestamp, None, None, latest.timestamp
    )
