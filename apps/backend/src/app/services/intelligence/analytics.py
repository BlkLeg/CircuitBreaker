"""Business Intelligence analytics: capacity forecasting, right-sizing, flap detection."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import (
    CapacityForecast,
    FlapIncident,
    HardwareLiveMetric,
    ResourceEfficiencyRecommendation,
)

_logger = logging.getLogger(__name__)


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """OLS regression returning (slope, intercept). Returns (0.0, mean(ys)) if n<2 or degenerate."""
    n = len(xs)
    if n < 2:
        mean_y = sum(ys) / n if n > 0 else 0.0
        return 0.0, mean_y

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0.0:
        return 0.0, sum_y / n

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def run_capacity_forecast(db: Session, lookback_days: int = 14, warning_days: int = 7) -> int:
    """Linear-regression capacity forecasts for all hardware with recent metrics.

    For each hardware_id with data in the lookback window:
    - Run OLS linear regression on disk_pct and mem_pct separately
    - slope_per_day = %/day growth rate
    - projected_full_at = utcnow() + timedelta(days=(100 - current) / slope) if slope > 0, else None
    - Upsert into CapacityForecast (update existing row if hardware_id+metric already exists)
    Returns: number of forecast rows upserted
    """
    now = utcnow()
    cutoff = now - timedelta(days=lookback_days)

    rows = (
        db.query(HardwareLiveMetric)
        .filter(HardwareLiveMetric.collected_at >= cutoff)
        .order_by(HardwareLiveMetric.hardware_id, HardwareLiveMetric.collected_at)
        .all()
    )

    # Group by hardware_id
    by_hw: dict[int, list[HardwareLiveMetric]] = {}
    for row in rows:
        by_hw.setdefault(row.hardware_id, []).append(row)

    upserted = 0
    for hw_id, metrics in by_hw.items():
        for metric_col in ("disk_pct", "mem_pct"):
            points = [
                (m.collected_at, getattr(m, metric_col))
                for m in metrics
                if getattr(m, metric_col) is not None
            ]
            if len(points) < 2:
                continue

            # Convert timestamps to float days relative to first point
            t0 = points[0][0]
            xs = [(ts - t0).total_seconds() / 86400.0 for ts, _ in points]
            ys = [v for _, v in points]

            slope, intercept = _linear_regression(xs, ys)

            # Current value = most recent
            current_value = ys[-1]

            projected_full_at: datetime | None = None
            if current_value >= 100.0:
                _logger.debug(
                    "hw %s metric %s already at/over 100%% (%.1f)",
                    hw_id,
                    metric_col,
                    current_value,
                )
            if slope > 0:
                days_left = (100.0 - current_value) / slope
                if days_left > 0:
                    projected_full_at = now + timedelta(days=days_left)

            # Upsert
            existing = db.execute(
                select(CapacityForecast).where(
                    CapacityForecast.hardware_id == hw_id,
                    CapacityForecast.metric == metric_col,
                )
            ).scalar_one_or_none()
            if existing is None:
                fc = CapacityForecast(
                    hardware_id=hw_id,
                    metric=metric_col,
                    slope_per_day=slope,
                    current_value=current_value,
                    projected_full_at=projected_full_at,
                    warning_threshold_days=warning_days,
                    evaluated_at=now,
                )
                db.add(fc)
            else:
                existing.slope_per_day = slope
                existing.current_value = current_value
                existing.projected_full_at = projected_full_at
                existing.warning_threshold_days = warning_days
                existing.evaluated_at = now

            upserted += 1

    db.flush()
    return upserted


def run_right_sizing(db: Session, lookback_days: int = 30) -> int:
    """Right-sizing classifications for all hardware with recent metrics.

    For each hardware_id:
    - cpu_avg > 75% OR (cpu_avg > 60% AND cpu_peak > 90%) -> "under_provisioned"
    - cpu_avg < 10% AND mem_avg < 15% -> "over_provisioned"
    - Otherwise -> "balanced"
    - Upsert into ResourceEfficiencyRecommendation
    Returns: number of recommendation rows upserted
    """
    now = utcnow()
    cutoff = now - timedelta(days=lookback_days)

    rows = db.query(HardwareLiveMetric).filter(HardwareLiveMetric.collected_at >= cutoff).all()

    by_hw: dict[int, list[HardwareLiveMetric]] = {}
    for row in rows:
        by_hw.setdefault(row.hardware_id, []).append(row)

    upserted = 0
    for hw_id, metrics in by_hw.items():
        cpu_vals = [m.cpu_pct for m in metrics if m.cpu_pct is not None]
        mem_vals = [m.mem_pct for m in metrics if m.mem_pct is not None]

        if not cpu_vals:
            continue

        cpu_avg = sum(cpu_vals) / len(cpu_vals)
        cpu_peak = max(cpu_vals)
        mem_avg = sum(mem_vals) / len(mem_vals) if mem_vals else 0.0

        if cpu_avg > 75.0 or (cpu_avg > 60.0 and cpu_peak > 90.0):
            classification = "under_provisioned"
            recommendation = (
                "CPU utilization is consistently high. Consider upgrading CPU or "
                "redistributing workloads."
            )
        elif cpu_avg < 10.0 and mem_avg < 15.0:
            classification = "over_provisioned"
            recommendation = (
                "CPU and memory utilization are very low. Consider downsizing or "
                "consolidating this node."
            )
        else:
            classification = "balanced"
            recommendation = "Resource utilization is within acceptable ranges."

        existing = db.execute(
            select(ResourceEfficiencyRecommendation).where(
                ResourceEfficiencyRecommendation.asset_type == "hardware",
                ResourceEfficiencyRecommendation.asset_id == hw_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            rec = ResourceEfficiencyRecommendation(
                asset_type="hardware",
                asset_id=hw_id,
                classification=classification,
                cpu_avg_pct=cpu_avg,
                cpu_peak_pct=cpu_peak,
                mem_avg_pct=mem_avg if mem_vals else None,
                recommendation=recommendation,
                evaluated_at=now,
            )
            db.add(rec)
        else:
            existing.classification = classification
            existing.cpu_avg_pct = cpu_avg
            existing.cpu_peak_pct = cpu_peak
            existing.mem_avg_pct = mem_avg if mem_vals else None
            existing.recommendation = recommendation
            existing.evaluated_at = now

        upserted += 1

    db.flush()
    return upserted


def run_flap_detection(db: Session, window_minutes: int = 30, min_transitions: int = 5) -> int:
    """Detect hardware nodes with rapid UP/DOWN transitions.

    For each hardware_id with status metrics in the window:
    - Count status transitions (consecutive rows with different status)
    - If transitions >= min_transitions: create/update active FlapIncident
    - If transitions < min_transitions: resolve any active FlapIncident
    Returns: number of new FlapIncident rows created
    """
    now = utcnow()
    cutoff = now - timedelta(minutes=window_minutes)

    rows = (
        db.query(HardwareLiveMetric)
        .filter(
            HardwareLiveMetric.collected_at >= cutoff,
            HardwareLiveMetric.status.isnot(None),
        )
        .order_by(HardwareLiveMetric.hardware_id, HardwareLiveMetric.collected_at)
        .all()
    )

    by_hw: dict[int, list[HardwareLiveMetric]] = {}
    for row in rows:
        by_hw.setdefault(row.hardware_id, []).append(row)

    created = 0
    for hw_id, metrics in by_hw.items():
        # Count transitions
        transitions = sum(
            1 for i in range(1, len(metrics)) if metrics[i].status != metrics[i - 1].status
        )

        existing = db.execute(
            select(FlapIncident).where(
                FlapIncident.asset_type == "hardware",
                FlapIncident.asset_id == hw_id,
                FlapIncident.is_active.is_(True),
            )
        ).scalar_one_or_none()

        if transitions >= min_transitions:
            window_start = metrics[0].collected_at
            window_end = metrics[-1].collected_at

            if existing is None:
                incident = FlapIncident(
                    asset_type="hardware",
                    asset_id=hw_id,
                    window_start=window_start,
                    window_end=window_end,
                    transition_count=transitions,
                    is_active=True,
                )
                db.add(incident)
                created += 1
            else:
                existing.window_end = window_end
                existing.transition_count = transitions
        else:
            if existing is not None:
                existing.is_active = False
                existing.resolved_at = now

    db.flush()
    return created
