"""Route severity is a floor, not an exact match (INC-03).

The UI has always labelled the field "Minimum Severity" with a "Severity
Threshold" column; the dispatcher compared it for equality, so a route set to
``info`` received info alerts and silently discarded warning and critical. This
module is the single place that decides what a threshold admits, so the label
and the behaviour cannot drift apart again.
"""

import pytest

from app.services.notification_severity import ROUTE_SEVERITIES, route_matches

_ALL_SEVERITIES = ("info", "warning", "critical")


@pytest.mark.parametrize("severity", _ALL_SEVERITIES)
def test_an_info_route_receives_every_severity_at_or_above_info(severity: str) -> None:
    assert route_matches("info", severity) is True


@pytest.mark.parametrize("severity", _ALL_SEVERITIES)
def test_the_wildcard_route_receives_everything(severity: str) -> None:
    assert route_matches("*", severity) is True


def test_a_warning_route_keeps_warning_and_critical_and_drops_info() -> None:
    assert route_matches("warning", "info") is False
    assert route_matches("warning", "warning") is True
    assert route_matches("warning", "critical") is True


def test_a_critical_route_receives_critical_only() -> None:
    assert route_matches("critical", "info") is False
    assert route_matches("critical", "warning") is False
    assert route_matches("critical", "critical") is True


def test_severity_comparison_ignores_case_and_padding() -> None:
    assert route_matches("warning", " CRITICAL ") is True
    assert route_matches(" Warning ", "info") is False


def test_common_severity_spellings_map_onto_the_ladder() -> None:
    assert route_matches("warning", "warn") is True
    assert route_matches("critical", "error") is True
    assert route_matches("critical", "warn") is False


def test_an_unrecognised_alert_severity_is_treated_as_critical() -> None:
    """Unknown urgency is delivered rather than dropped — this finding's whole point."""
    assert route_matches("critical", "meltdown") is True
    assert route_matches("info", "meltdown") is True


def test_an_unrecognised_route_threshold_delivers_everything() -> None:
    """A legacy or hand-written row must not become a silent black hole."""
    for severity in _ALL_SEVERITIES:
        assert route_matches("verbose", severity) is True


def test_route_severities_are_the_choices_the_api_accepts() -> None:
    assert ROUTE_SEVERITIES == ("*", "info", "warning", "critical")
