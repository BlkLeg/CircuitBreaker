"""Finite catalog and history adapter for supported hardware gauges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Hardware, HardwareLiveMetric
from app.schemas.metric_alerts import MetricDefinition

CATALOG = {
    "cpu_pct": MetricDefinition(
        key="cpu_pct",
        label="CPU utilization",
        unit="%",
        comparators=[">", ">=", "<", "<="],
        target_types=["hardware"],
        default_freshness_s=180,
        default_max_gap_s=180,
    ),
    "mem_pct": MetricDefinition(
        key="mem_pct",
        label="Memory utilization",
        unit="%",
        comparators=[">", ">=", "<", "<="],
        target_types=["hardware"],
        default_freshness_s=180,
        default_max_gap_s=180,
    ),
    "disk_pct": MetricDefinition(
        key="disk_pct",
        label="Disk utilization",
        unit="%",
        comparators=[">", ">=", "<", "<="],
        target_types=["hardware"],
        default_freshness_s=300,
        default_max_gap_s=300,
    ),
    "temp_c": MetricDefinition(
        key="temp_c",
        label="Temperature",
        unit="°C",
        comparators=[">", ">=", "<", "<="],
        target_types=["hardware"],
        default_freshness_s=180,
        default_max_gap_s=180,
    ),
    "power_w": MetricDefinition(
        key="power_w",
        label="Power",
        unit="W",
        comparators=[">", ">=", "<", "<="],
        target_types=["hardware"],
        default_freshness_s=180,
        default_max_gap_s=180,
    ),
}


@dataclass(frozen=True)
class MetricSample:
    timestamp: datetime
    value: float
    sample_id: str


def list_metric_definitions() -> list[MetricDefinition]:
    return list(CATALOG.values())


def validate_target(db: Session, target_type: str, target_id: int) -> None:
    if target_type != "hardware" or db.get(Hardware, target_id) is None:
        raise ValueError("The selected hardware target does not exist")


def read_metric_window(
    db: Session,
    *,
    target_id: int,
    metric_key: str,
    since: datetime,
    source: str | None = None,
    limit: int = 5000,
) -> list[MetricSample]:
    definition = CATALOG.get(metric_key)
    if definition is None:
        raise ValueError("Unsupported metric")
    column = getattr(HardwareLiveMetric, metric_key)
    query = db.query(
        HardwareLiveMetric.id,
        HardwareLiveMetric.collected_at,
        HardwareLiveMetric.agent_sample_id,
        column.label("value"),
    ).filter(
        HardwareLiveMetric.hardware_id == target_id,
        HardwareLiveMetric.collected_at >= since,
        column.isnot(None),
        HardwareLiveMetric.source != "hourly_agg",
    )
    if source:
        query = query.filter(HardwareLiveMetric.source == source)
    rows = query.order_by(HardwareLiveMetric.collected_at.desc()).limit(limit).all()
    return [
        MetricSample(
            timestamp=row.collected_at,
            value=float(row.value),
            sample_id=row.agent_sample_id or f"{row.id}:{row.collected_at.isoformat()}",
        )
        for row in reversed(rows)
    ]
