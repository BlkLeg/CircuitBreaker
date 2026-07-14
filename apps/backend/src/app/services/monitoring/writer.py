"""Bulk-write collector Samples into the telemetry_timeseries hypertable."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample

SampleRow = tuple[int, str, int | None, list[Sample], datetime]


def write_samples(db: Session, rows: list[SampleRow]) -> int:
    """Insert all samples from a batch of polled items in one bulk statement.

    Caller owns the transaction (commit/rollback). Returns the row count.
    """
    mappings: list[dict] = []
    for item_id, entity_type, entity_id, samples, ts in rows:
        for s in samples:
            mappings.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id if entity_id is not None else 0,
                    "item_id": item_id,
                    "metric": s.metric,
                    "value": s.value,
                    "source": "monitor",
                    "ts": ts,
                }
            )
    if mappings:
        db.bulk_insert_mappings(TelemetryTimeseries, mappings)
    return len(mappings)
