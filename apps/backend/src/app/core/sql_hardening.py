"""Helpers for safe dynamic SQL identifier construction."""

from __future__ import annotations

import re
from datetime import datetime

_AUDIT_PARTITION_NAME_RE = re.compile(r"^audit_log_[0-9]{4}_(0[1-9]|1[0-2])$")


def quote_audit_partition_name(name: str) -> str:
    """Return a quoted audit partition identifier after strict validation."""
    if not _AUDIT_PARTITION_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid audit partition name: {name!r}")
    return f'"{name}"'


def build_audit_partition_sql(anchor: datetime) -> str:
    """Build deterministic SQL for a monthly audit_log partition."""
    partition_name = f"audit_log_{anchor.year}_{anchor.month:02d}"
    if anchor.month == 12:
        next_year = anchor.year + 1
        next_month = 1
    else:
        next_year = anchor.year
        next_month = anchor.month + 1
    start = f"{anchor.year}-{anchor.month:02d}-01"
    end = f"{next_year}-{next_month:02d}-01"
    return (
        "CREATE TABLE IF NOT EXISTS "
        f"{quote_audit_partition_name(partition_name)} "
        "PARTITION OF audit_log "
        f"FOR VALUES FROM ('{start}') TO ('{end}')"
    )
