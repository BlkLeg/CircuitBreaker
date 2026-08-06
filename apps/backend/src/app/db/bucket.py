"""Portable time bucketing for history/aggregate queries.

The backend is PostgreSQL-only but **TimescaleDB-optional**: `Dockerfile.mono`
installs the extension while `docker-compose.deps.yml` runs plain
`postgres:16-alpine`, and the hypertable migrations bail out when the extension
is absent. `time_bucket()` is therefore off limits in application queries; this
module is the one place that expresses "floor a timestamp onto an epoch grid"
so callers do not each re-derive it.

Every per-agent read built on top of this must still filter on both the entity
id and a timestamp range, so hypertable chunk exclusion keeps working.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, extract, func
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.expression import ColumnExpressionArgument


def epoch_bucket(
    column: ColumnExpressionArgument[datetime], width_seconds: int
) -> ColumnElement[datetime]:
    """Floor `column` onto a UTC epoch grid of `width_seconds`.

    Renders `to_timestamp(floor(extract(epoch from <column>) / w) * w)`, which
    works on any PostgreSQL 12+ server with or without TimescaleDB. Buckets are
    aligned to the epoch itself — not to the first row in the result — so two
    requests issued seconds apart return the same bucket boundaries.

    The result is a `timestamptz`, so values come back timezone-aware.
    """
    if width_seconds <= 0:
        raise ValueError("width_seconds must be positive")
    width = float(width_seconds)
    return func.to_timestamp(
        func.floor(extract("epoch", column) / width) * width,
        type_=DateTime(timezone=True),
    )
