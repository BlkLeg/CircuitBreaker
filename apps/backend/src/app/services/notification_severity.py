"""Notification route severity thresholds.

The route field is labelled **"Minimum Severity"** and rendered under a
**"Severity Threshold"** column, but the dispatcher compared it for equality
(``route.alert_severity == severity``). A route set to ``info`` therefore
received info alerts and silently discarded warning and critical ones — the
opposite of what the label promises, and a failure in the dangerous direction
(INC-03). Severity is the only routing key ``NotificationRoute`` has, so when it
filters wrongly there is nothing else to catch the alert.

This module is the single place that decides what a threshold admits, so the
label and the behaviour cannot drift apart again — the same reason
``notification_secrets`` owns the decision about which config keys are secret.

Two deliberate asymmetries, both of which fail toward delivering:

- An alert whose severity is not on the ladder ranks as ``critical``, so it
  reaches every route rather than none. Unknown urgency is not an excuse to
  stay silent.
- A route whose stored threshold is not on the ladder — a legacy row, or one
  hand-written before the API validated the field — admits everything rather
  than becoming a black hole. New rows cannot get into that state: the API
  accepts only ``ROUTE_SEVERITIES``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The wildcard predates the threshold and is still what "All Events" stores.
SEVERITY_ANY = "*"

# Ordered least to most urgent; position in this tuple *is* the rank.
SEVERITY_LADDER: tuple[str, ...] = ("info", "warning", "critical")

# What the UI offers and the API accepts for NotificationRoute.alert_severity.
ROUTE_SEVERITIES: tuple[str, ...] = (SEVERITY_ANY, *SEVERITY_LADDER)

# Alerts arrive from any publisher on ``alert.>``; route thresholds are ours.
# So spellings are tolerated on the alert side only — the API rejects them.
_SEVERITY_ALIASES: dict[str, str] = {
    "warn": "warning",
    "err": "critical",
    "error": "critical",
    "fatal": "critical",
    "alert": "critical",
    "emergency": "critical",
    "debug": "info",
    "notice": "info",
}

_UNREADABLE_ALERT_SEVERITY = "critical"


def _canonical_severity(value: object) -> str | None:
    """Fold a severity onto the ladder, or ``None`` if it is not on it."""
    name = str(value).strip().lower()
    if name in SEVERITY_LADDER:
        return name
    return _SEVERITY_ALIASES.get(name)


def alert_severity_rank(severity: object) -> int:
    """Rank an incoming alert. Unreadable urgency ranks highest, never lowest."""
    name = _canonical_severity(severity)
    if name is None:
        logger.warning(
            "[notification_severity] alert severity %r is not on the ladder; "
            "treating it as %s so it is delivered rather than dropped",
            severity,
            _UNREADABLE_ALERT_SEVERITY,
        )
        name = _UNREADABLE_ALERT_SEVERITY
    return SEVERITY_LADDER.index(name)


def route_matches(threshold: object, severity: object) -> bool:
    """Does a route with this threshold accept an alert of this severity?

    ``threshold`` is a floor, not an exact match: ``warning`` admits warning and
    critical, ``critical`` admits critical only, and ``*`` admits everything.
    """
    if str(threshold).strip().lower() == SEVERITY_ANY:
        return True
    floor = _canonical_severity(threshold)
    if floor is None:
        logger.warning(
            "[notification_severity] route threshold %r is not one of %s; "
            "delivering every severity to it rather than none",
            threshold,
            ", ".join(ROUTE_SEVERITIES),
        )
        return True
    return alert_severity_rank(severity) >= SEVERITY_LADDER.index(floor)
