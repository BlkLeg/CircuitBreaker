"""RC-05: the service objectives must have a measurement source in the product.

RC-05's acceptance is "targets and measurement windows are published; SRV-03
and REL-21 tests produce the named metrics". The targets were published against
instrumentation that did not exist: `/api/v1/metrics` exposed inventory counts
and per-service status, and nothing measured availability, latency, health
state or backlog — so every objective was a number with no way to tell whether
it was met.

These tests exercise the server and then read the metrics back out of the
endpoint an operator scrapes, which is the only place the claim can be true.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core import health, slo_metrics, write_admission
from app.core.server_state import ServerState, get_state, set_state

# The availability series for /api/v1/livez, named once so the label set the
# baseline reads and the one the assertion reads cannot drift apart.
_LIVEZ_2XX = '{method="GET",route="/api/v1/livez",status_class="2xx"}'


@pytest.fixture(autouse=True)
def _isolated_health_state():
    previous_state = get_state()
    previous_armed = write_admission.is_armed()
    set_state(ServerState.READY)
    health.reset_cache()
    yield
    set_state(previous_state)
    health.reset_cache()
    if previous_armed:
        write_admission.arm()
    else:
        write_admission.disarm()


def _families(exposition: str) -> set[str]:
    """Metric family names in an exposition, including families that currently
    have no samples — a counter that has not been incremented yet still has to
    be *declared*, or a dashboard cannot be built before the first event."""
    names: set[str] = set()
    for line in exposition.splitlines():
        if line.startswith("# HELP "):
            names.add(line.split()[2])
        elif line and not line.startswith("#"):
            names.add(line.split(" ")[0].split("{")[0])
    return names


def _sample(exposition: str, name: str, labels: str = "") -> float | None:
    prefix = f"{name}{labels}"
    for line in exposition.splitlines():
        if line.startswith(prefix) and (
            len(line) > len(prefix) and line[len(prefix)] in " {" or line.startswith(prefix + " ")
        ):
            if labels and not line.startswith(prefix):
                continue
            try:
                return float(line.rsplit(" ", 1)[1])
            except ValueError:  # pragma: no cover - malformed exposition
                return None
    return None


async def _scrape(client: AsyncClient, headers: dict) -> str:
    response = await client.get("/api/v1/metrics/metrics", headers=headers)
    assert response.status_code == 200, response.text
    return response.text


async def test_the_named_slo_metrics_are_emitted(client: AsyncClient, auth_headers):
    """Every objective in docs/release/1.0.0-service-objectives.md that this
    server can measure has a series here."""
    await client.get("/api/v1/livez")

    body = await _scrape(client, auth_headers)
    names = _families(body)

    for required in (
        # API availability and latency
        "circuitbreaker_http_requests_total",
        "circuitbreaker_http_request_duration_seconds_bucket",
        # RC-05 health-state contract
        "circuitbreaker_health_state",
        # SRV-03 enforcement
        "circuitbreaker_write_admission_rejections_total",
        # Background processing
        "circuitbreaker_background_job_runs_total",
        # Monitoring execution freshness
        "circuitbreaker_monitor_checks_overdue",
        "circuitbreaker_monitor_check_lag_seconds",
        # §5 objective 1 reads this one, not the gauge above it: that one only
        # counts checks more than two intervals late, so against a 30s Tier C
        # interval it is 0.0 for every lag the objective is about.
        "circuitbreaker_monitor_scheduling_lag_seconds",
        # Backlog and agent presence
        "circuitbreaker_scan_job_backlog",
        "circuitbreaker_agents_present",
        "circuitbreaker_agent_presence_age_seconds",
    ):
        assert required in names, f"{required} is not exposed by /api/v1/metrics"


async def test_requests_are_counted_by_route_template_and_status_class(
    client: AsyncClient, auth_headers
):
    """The availability indicator. Labelled by route *template*: the raw path
    carries object ids, and one time series per inventory row is the cardinality
    failure SRV-09 forbids."""
    before = await _scrape(client, auth_headers)
    baseline = _sample(before, "circuitbreaker_http_requests_total", _LIVEZ_2XX) or 0.0

    for _ in range(3):
        await client.get("/api/v1/livez")

    after = await _scrape(client, auth_headers)
    counted = _sample(after, "circuitbreaker_http_requests_total", _LIVEZ_2XX)
    assert counted == pytest.approx(baseline + 3)


async def test_latency_is_observed_for_the_route(client: AsyncClient, auth_headers):
    await client.get("/api/v1/livez")

    body = await _scrape(client, auth_headers)

    count = _sample(
        body,
        "circuitbreaker_http_request_duration_seconds_count",
        '{method="GET",route="/api/v1/livez"}',
    )
    assert count is not None and count >= 1
    # The RC-05 latency objective is written at p95 < 500 ms, so 0.5 has to be
    # a bucket edge or the target cannot be evaluated from the histogram.
    assert 'le="0.5"' in body


async def test_an_object_id_never_becomes_a_metric_label(client: AsyncClient, auth_headers):
    """A path with an id in it must collapse onto its template."""
    await client.get("/api/v1/hardware/424242", headers=auth_headers)

    body = await _scrape(client, auth_headers)

    assert "424242" not in body


async def test_the_health_state_is_a_series(client: AsyncClient, monkeypatch, auth_headers):
    """ "How long was it degraded" has to be answerable after the fact, which
    means the RC-05 state has to be recorded, not only returned to a probe."""
    import app.core.redis as redis_module

    monkeypatch.setattr(health, "_probe_db", lambda: "ok")

    async def _redis_down() -> bool:
        return False

    monkeypatch.setattr(redis_module, "redis_health", _redis_down)
    await client.get("/api/v1/readyz")

    body = await _scrape(client, auth_headers)

    assert _sample(body, "circuitbreaker_health_state", '{state="degraded"}') == 1.0
    assert _sample(body, "circuitbreaker_health_state", '{state="ready"}') == 0.0
    assert _sample(body, "circuitbreaker_health_state", '{state="not_ready"}') == 0.0


async def test_a_refused_write_is_counted(client: AsyncClient, monkeypatch, auth_headers):
    """SRV-03's enforcement has to be observable: an operator needs to see that
    readiness refused work, not only that a dependency was down."""
    baseline = (
        _sample(
            await _scrape(client, auth_headers),
            "circuitbreaker_write_admission_rejections_total",
            '{health="not_ready"}',
        )
        or 0.0
    )
    monkeypatch.setattr(health, "_probe_db", lambda: "error")
    health.reset_cache()

    response = await client.post("/api/v1/hardware", json={"name": "nas"}, headers=auth_headers)
    assert response.status_code == 503

    monkeypatch.setattr(health, "_probe_db", lambda: "ok")
    health.reset_cache()
    body = await _scrape(client, auth_headers)

    assert (
        _sample(
            body,
            "circuitbreaker_write_admission_rejections_total",
            '{health="not_ready"}',
        )
        == baseline + 1
    )


def test_a_skipped_job_is_counted_as_such(monkeypatch):
    """SRV-02's single-owner claim is only auditable if "another process owned
    it" is distinguishable from "it never ran"."""
    from app.core.job_lock import (
        _lock_id_for,
        advisory_unlock,
        lock_session,
        single_owner,
        try_advisory_lock,
    )

    job_id = "test_slo_skip_probe"
    lock_id = _lock_id_for("scheduled_job", job_id)
    holder = lock_session()
    assert try_advisory_lock(holder, lock_id)
    try:
        single_owner(lambda: None, job_id=job_id)()
    finally:
        advisory_unlock(holder, lock_id)
        holder.close()

    exposition = slo_metrics.exposition().decode()
    assert (
        _sample(
            exposition,
            "circuitbreaker_background_job_runs_total",
            f'{{job="{job_id}",outcome="skipped_not_owner"}}',
        )
        == 1.0
    )


async def test_metrics_still_require_authentication(client: AsyncClient):
    """The new series carry operational detail; the endpoint's existing auth
    model must not have been widened to publish them."""
    assert (await client.get("/api/v1/metrics/metrics")).status_code == 401


@pytest.mark.asyncio
async def test_scheduling_lag_is_measurable_below_two_intervals(
    client, auth_headers, db_session, factories
):
    """M12. §5's first objective is "monitor scheduling lag < the shortest
    supported poll interval" — 30s at Tier C. It was scored against
    `circuitbreaker_monitor_check_lag_seconds`, which reports the oldest check
    *more than two intervals* past due. Against a 30s interval that gauge reads
    0.0 for every lag below 60s and jumps straight past the target once it is
    non-zero, so "passed" collapsed to "lag == 0" and the region the objective
    describes had no resolution at all.

    A check 45s late against a 30s interval is exactly the case that matters: it
    misses the target and is not yet two intervals overdue.
    """
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import MonitorItem

    item = MonitorItem(
        name="cb-test-m12",
        host="192.0.2.10",
        target_type="hardware",
        target_id=factories.hardware().id,
        check_type="ping",
        interval_secs=30,
        enabled=True,
        next_due_at=utcnow() - timedelta(seconds=45),
    )
    db_session.add(item)
    db_session.commit()

    body = await _scrape(client, auth_headers)

    old_gauge = _sample(body, "circuitbreaker_monitor_check_lag_seconds")
    new_gauge = _sample(body, "circuitbreaker_monitor_scheduling_lag_seconds")

    assert old_gauge == 0.0, "the two-interval gauge cannot see a 45s lag on a 30s interval"
    assert new_gauge >= 45.0, "the scheduling-lag gauge must report the real lateness"
