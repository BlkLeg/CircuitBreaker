"""The load generator's Prometheus parsing, against real exposition text.

Every number in a Phase 2 baseline comes out of these two functions, and a
mistake in either produces a plausible wrong number rather than an error. Both
had one: `gauge_value`'s predecessor matched by prefix and could return the
histogram's value for the gauge, and `histogram_quantile`'s took the largest
finite bucket as the total observation count, which biases every quantile low in
exactly the slow-tail case a p99 exists to expose.
"""

from __future__ import annotations

from scripts.loadgen.run import (
    gauge_value,
    histogram_quantile,
    percentile,
    websocket_base,
)

# A gauge and a histogram whose names differ only by suffix — the exact shape
# `circuitbreaker_event_loop_lag_seconds` and its `_hist` companion have.
EXPOSITION = """\
# HELP circuitbreaker_event_loop_lag_seconds Most recent lag
# TYPE circuitbreaker_event_loop_lag_seconds gauge
circuitbreaker_event_loop_lag_seconds 0.004
# HELP circuitbreaker_event_loop_lag_seconds_hist Distribution
# TYPE circuitbreaker_event_loop_lag_seconds_hist histogram
circuitbreaker_event_loop_lag_seconds_hist_bucket{le="0.001"} 10.0
circuitbreaker_event_loop_lag_seconds_hist_bucket{le="0.005"} 80.0
circuitbreaker_event_loop_lag_seconds_hist_bucket{le="0.01"} 90.0
circuitbreaker_event_loop_lag_seconds_hist_bucket{le="+Inf"} 100.0
circuitbreaker_event_loop_lag_seconds_hist_count 100.0
"""


def test_a_gauge_is_not_confused_with_the_histogram_that_shares_its_prefix() -> None:
    assert gauge_value(EXPOSITION, "circuitbreaker_event_loop_lag_seconds") == 0.004


def test_a_missing_gauge_reads_as_unmeasured_rather_than_zero() -> None:
    assert gauge_value(EXPOSITION, "circuitbreaker_not_exported") is None
    assert gauge_value("", "circuitbreaker_event_loop_lag_seconds") is None


def test_the_quantile_denominator_is_the_inf_bucket() -> None:
    """90 of 100 observations are ≤ 10 ms, so p95 is above that bucket.

    Counting only the finite buckets would put the total at 90, drop the rank
    threshold to 85.5, and answer 10 ms — a p95 that ignores every sample slower
    than the largest bucket edge, which is the population the number is about.
    """
    assert histogram_quantile(EXPOSITION, "circuitbreaker_event_loop_lag_seconds_hist", 0.5) == 0.005
    assert histogram_quantile(EXPOSITION, "circuitbreaker_event_loop_lag_seconds_hist", 0.95) == 0.01


def test_a_histogram_with_no_observations_reads_as_unmeasured() -> None:
    empty = (
        'circuitbreaker_x_bucket{le="0.1"} 0.0\n'
        'circuitbreaker_x_bucket{le="+Inf"} 0.0\n'
    )
    assert histogram_quantile(empty, "circuitbreaker_x", 0.95) is None
    assert histogram_quantile("", "circuitbreaker_x", 0.95) is None


def test_percentile_is_nearest_rank_and_empty_safe() -> None:
    assert percentile([], 0.95) is None
    assert percentile([1.0], 0.95) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_websocket_base_preserves_the_scheme_it_was_given() -> None:
    assert websocket_base("http://127.0.0.1:8000") == "ws://127.0.0.1:8000"
    assert websocket_base("https://cb.example.test/") == "wss://cb.example.test"
