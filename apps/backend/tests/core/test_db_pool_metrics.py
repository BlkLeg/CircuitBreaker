"""Connection-pool saturation metrics (route §5).

Route §5 lists "DB pool utilization + `pool_timeout` events" among the things
measured at every tier, and the Phase 2 load generator has a `db_pool` block in
every result document. That block shipped reading
`circuitbreaker_db_pool_checked_out` and `circuitbreaker_db_pool_size`, neither
of which existed anywhere in the backend, so it was `null` in every report ever
produced — which reads as a quiet, idle pool rather than as no measurement.
These tests exist so the series stay real.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core import slo_metrics


def _sample(name: str) -> float:
    """Current value of an unlabelled gauge or counter in the process registry."""
    value = slo_metrics.REGISTRY.get_sample_value(name)
    assert value is not None, f"{name} is not exposed by the process-lifetime registry"
    return float(value)


def test_the_pool_series_are_exposed_under_the_names_the_harness_reads() -> None:
    """The names are the contract; the load generator reads them literally."""
    exposition = slo_metrics.exposition().decode("utf-8")
    for metric_name in (
        "circuitbreaker_db_pool_size",
        "circuitbreaker_db_pool_checked_out",
        "circuitbreaker_db_pool_checked_in",
        "circuitbreaker_db_pool_overflow",
        "circuitbreaker_db_pool_timeouts_total",
    ):
        assert metric_name in exposition, f"{metric_name} is missing from the exposition"


def test_refreshing_the_gauges_reads_the_live_pool() -> None:
    """A scrape publishes the engine's actual configured size, not a constant."""
    from app.db.session import engine

    slo_metrics.refresh_db_pool_gauges()
    assert _sample("circuitbreaker_db_pool_size") == float(engine.pool.size())
    # Occupancy is a real, non-negative reading rather than a placeholder.
    assert _sample("circuitbreaker_db_pool_checked_out") >= 0


def test_a_pool_without_counters_leaves_the_gauges_alone(monkeypatch: Any) -> None:
    """`NullPool` has nothing to report, and zeros would be a false reading.

    Publishing 0 for a pool that cannot be measured would show up in a baseline
    as a completely idle connection pool, which is a different claim from "not
    measured".
    """
    from sqlalchemy.pool import NullPool

    import app.db.session as db_session

    slo_metrics.refresh_db_pool_gauges()
    before = _sample("circuitbreaker_db_pool_size")

    class _Unmeasurable:
        # A NullPool instance needs a real `creator`; the type is what the guard
        # checks, so an unconnected instance built from it is enough.
        pool = NullPool(creator=lambda: None)

    monkeypatch.setattr(db_session, "engine", _Unmeasurable, raising=True)
    slo_metrics.refresh_db_pool_gauges()

    assert _sample("circuitbreaker_db_pool_size") == before


def test_a_broken_pool_read_does_not_fail_the_scrape(monkeypatch: Any) -> None:
    """Instrumentation must never be what takes the metrics endpoint down.

    `exposition()` calls this refresh on every scrape, so an engine in a bad
    state has to degrade to stale gauges rather than to a 500 on the endpoint an
    operator reaches for precisely when things are going wrong.
    """
    import app.db.session as db_session

    class _ExplodingEngine:
        @property
        def pool(self) -> Any:
            raise RuntimeError("pool is gone")

    monkeypatch.setattr(db_session, "engine", _ExplodingEngine(), raising=True)

    slo_metrics.refresh_db_pool_gauges()  # must not raise
    assert b"circuitbreaker_db_pool_size" in slo_metrics.exposition()


def test_a_pool_timeout_is_counted_once_per_exhausted_request() -> None:
    """`get_db` is the choke point every request's session passes through."""
    from app.db.session import _count_if_pool_timeout

    before = _sample("circuitbreaker_db_pool_timeouts_total")
    _count_if_pool_timeout(SQLAlchemyTimeoutError("QueuePool limit reached"))
    assert _sample("circuitbreaker_db_pool_timeouts_total") == before + 1


def test_an_unrelated_failure_is_not_counted_as_a_pool_timeout() -> None:
    """A statement timeout and an exhausted pool are different faults.

    Conflating them would make the one metric that says "add connections" fire
    for problems more connections cannot fix.
    """
    from app.db.session import _count_if_pool_timeout

    before = _sample("circuitbreaker_db_pool_timeouts_total")
    _count_if_pool_timeout(TimeoutError("statement timeout"))
    _count_if_pool_timeout(ValueError("something else entirely"))
    assert _sample("circuitbreaker_db_pool_timeouts_total") == before
